import yfinance as yf
import pandas as pd
import warnings
import json
import logging
import sys
import os
from datetime import date, timedelta

# Silence noisy library warnings from yfinance/pandas; real errors still
# propagate as exceptions and are not affected by this filter.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Diagnostic logging only: goes to stderr (or nowhere, by default logging
# config), never stdout, since stdout must stay the single-line ticker
# output that status bars render verbatim.
logger = logging.getLogger(__name__)


def load_portfolio(filename: str = "portfolio.json") -> dict[str, list[list]]:
    """Loads the portfolio from a JSON file, searching for it in the same directory as the script."""
    # Calculate the absolute path for the configuration file
    # based on the script's location.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, filename)
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"Error: Configuration file '{config_path}' not found.")
    except json.JSONDecodeError:
        sys.exit(f"Error: The file '{config_path}' is not a valid JSON.")


def _closing_price_on_or_before(
    hist: pd.DataFrame, target_date: date, fallback: float, strictly_before: bool = False
) -> float:
    """Return the last closing price in `hist` on or before `target_date`.

    Falls back to `fallback` if `hist` is empty or has no matching rows.

    `strictly_before=True` excludes `target_date` itself, returning the
    close of the session immediately preceding it instead. Used for the
    1M/YTD/1Y reference prices: those `target_date`s are calendar-day
    approximations of "N ago" that stand for the *start* of that trailing
    window, not its own end — confirmed against Yahoo's own portfolio
    baseline for 1M, whose reference price is the prior session's close
    even though the calendar-approximated date itself is a real trading
    day with its own close. This mirrors how 5D's reference date is
    already the session *before* the first day of the measured window
    (see `_n_trading_sessions_ago`), just reached via a calendar
    approximation here instead of exact session counting. The default
    (`False`, on-or-before) stays as-is for resolving an *already*
    precisely-known session's price (`_n_trading_sessions_ago`'s internal
    use), where a NaN close should fall back to the latest prior valid
    one but a valid close on that exact session must still win.
    """
    if hist.empty:
        return fallback
    if strictly_before:
        prior_rows = hist[hist.index.date < target_date]
    else:
        prior_rows = hist[hist.index.date <= target_date]
    if prior_rows.empty:
        return fallback
    return prior_rows['Close'].iloc[-1]


def _n_trading_sessions_ago(
    hist: pd.DataFrame, valid_hist: pd.DataFrame, n: int, fallback_date: date, fallback_price: float
) -> tuple[date, float]:
    """Return the (date, closing price) of the trading session `n` sessions before the most recent completed session in `hist`.

    Falls back to `(fallback_date, fallback_price)` if fewer than `n` prior
    sessions are available. Used for `5D`: Yahoo Finance counts trading
    sessions, not calendar days, and a plain 5-calendar-day lookback often
    only spans 3-4 actual sessions once a weekend is in the window,
    understating a period this short far more than it does the longer ones.

    Session *positions* are counted against `hist` with only a trailing run
    of NaN-close rows trimmed (an unsettled "today" bar) — not every NaN
    row, as `valid_hist` does. Yahoo occasionally comes back with a NaN
    close for an *interior* day, not just the still-forming last bar;
    silently excluding that day from the count (as counting against
    `valid_hist` would) shifts every session position one day too far back.
    Once the target session's date is found this way, its actual price is
    read from `valid_hist` via `_closing_price_on_or_before`, which falls
    back to the latest valid close before that date if the target
    session's own close is itself the NaN one.
    """
    last_valid_idx = hist['Close'].last_valid_index()
    session_calendar = hist.loc[:last_valid_idx] if last_valid_idx is not None else hist.iloc[0:0]
    if len(session_calendar) <= n:
        return fallback_date, fallback_price
    target_date = session_calendar.index[-(n + 1)].date()
    return target_date, _closing_price_on_or_before(valid_hist, target_date, fallback_price)


def _last_intraday_close(hourly_hist: pd.DataFrame, target_date: date, fallback: float) -> float:
    """Return the last hourly closing price recorded on `target_date`.

    Falls back to `fallback` if `hourly_hist` has no rows on that date.
    Yahoo Finance's own `5D` figure is anchored to the last *intraday*
    trade before the window starts, not the end-of-day official closing
    price `_n_trading_sessions_ago` reads from daily bars — for
    low-volatility instruments those two can differ by a cent or more,
    which is disproportionate for a period this short. Confirmed by
    reading Yahoo's own portfolio-performance-chart API response and
    matching its `baseline` field to the cent.
    """
    if hourly_hist.empty:
        return fallback
    day_rows = hourly_hist[hourly_hist.index.date == target_date]
    if day_rows.empty:
        return fallback
    return day_rows['Close'].iloc[-1]


def _fetch_regular_market_previous_close(ticker: yf.Ticker, symbol: str) -> float | None:
    """Fetch Yahoo's official previous-close price via its live quote endpoint.

    Returns `None` on any failure — network error, an unexpected response
    shape, or the field itself being absent/NaN — so callers can fall back
    to a chart-derived estimate.

    This is a *different* data source from `history()`'s daily/hourly bars:
    it's the exchange's official closing-auction price, straight from
    Yahoo's live quote system. Confirmed live: for a session whose daily
    bar Yahoo's chart endpoint returns as entirely NaN (a genuine data gap,
    not a holiday — see the `keepna=True` comment in `get_performance()`),
    this still returns the correct official close, while even an
    hourly-bar-refined estimate for that same session was off by several
    cents — hourly bars only capture continuous-trading prints, not the
    closing auction that settles the official close.

    Uses `yfinance`'s internal `Ticker._data` session (undocumented, but
    it's the same session/cookie/crumb machinery every other call in this
    module already goes through) to call Yahoo's `v7/finance/quote`
    directly instead of the heavier public `Ticker.info` (which bundles in
    a `quoteSummary` request this module has no other use for).
    """
    try:
        response = ticker._data.get_raw_json(
            "https://query1.finance.yahoo.com/v7/finance/quote", params={"symbols": symbol}
        )
        value = response["quoteResponse"]["result"][0]["regularMarketPreviousClose"]
        return None if pd.isna(value) else float(value)
    except Exception:
        return None


def _value_as_of(lots: list[list], target_date: date, market_price: float) -> float:
    """Value a ticker's lots as they stood on `target_date`.

    `target_date` is a *start-of-period* anchor (yesterday, 5D/1M/YTD/1Y
    ago) — the baseline a period's growth is measured from, not its end.
    Lots already purchased strictly before `target_date` are valued at
    `market_price` (what they were actually worth then). Lots purchased on
    or after `target_date` didn't yet form part of that baseline — a
    purchase made on that exact date is part of what happened *during* the
    period being measured, not before it — so they're valued at their own
    purchase cost instead. Otherwise a period would price shares you didn't
    hold yet as part of the baseline, overstating it and understating the
    period's real gain. Confirmed against Yahoo's own portfolio baseline
    for a purchase landing exactly on a reference date: Yahoo excludes it
    the same way.
    """
    total = 0.0
    for shares, cost, purchase_date in lots:
        if date.fromisoformat(purchase_date) < target_date:
            total += shares * market_price
        else:
            total += shares * cost
    return total


def format_performance(
    total_cost: float,
    current_total_value: float,
    yesterday_total_value: float,
    five_days_start_total_value: float,
    one_month_start_total_value: float,
    ytd_start_total_value: float,
    year_start_total_value: float,
) -> str:
    """Compute daily/5D/1M/YTD/1Y/total performance and format the ticker string.

    Pure function (no I/O): all inputs are already-aggregated portfolio
    totals in the same currency (EUR), which makes it testable without
    mocking yfinance.
    """
    if total_cost == 0:
        return "ETF: Error"

    daily_net = current_total_value - yesterday_total_value
    daily_perc = (daily_net / yesterday_total_value) * 100 if yesterday_total_value != 0 else 0
    five_days_net = current_total_value - five_days_start_total_value
    five_days_perc = (
        (five_days_net / five_days_start_total_value) * 100 if five_days_start_total_value != 0 else 0
    )
    one_month_net = current_total_value - one_month_start_total_value
    one_month_perc = (
        (one_month_net / one_month_start_total_value) * 100 if one_month_start_total_value != 0 else 0
    )
    ytd_net = current_total_value - ytd_start_total_value
    ytd_perc = (ytd_net / ytd_start_total_value) * 100 if ytd_start_total_value != 0 else 0
    year_net = current_total_value - year_start_total_value
    year_perc = (year_net / year_start_total_value) * 100 if year_start_total_value != 0 else 0
    total_net = current_total_value - total_cost
    total_perc = (total_net / total_cost) * 100 if total_cost != 0 else 0

    d_icon = "▲" if daily_net >= 0 else "▼"
    five_days_icon = "▲" if five_days_net >= 0 else "▼"
    one_month_icon = "▲" if one_month_net >= 0 else "▼"
    ytd_icon = "▲" if ytd_net >= 0 else "▼"
    y_icon = "▲" if year_net >= 0 else "▼"
    t_icon = "▲" if total_net >= 0 else "▼"

    return (
        f"1D: {d_icon} {daily_perc:.2f}% ({daily_net:+.2f}€) | "
        f"5D: {five_days_icon} {five_days_perc:.2f}% ({five_days_net:+.2f}€) | "
        f"1M: {one_month_icon} {one_month_perc:.2f}% ({one_month_net:+.2f}€) | "
        f"YTD: {ytd_icon} {ytd_perc:.2f}% ({ytd_net:+.2f}€) | "
        f"1Y: {y_icon} {year_perc:.2f}% ({year_net:+.2f}€) | "
        f"T: {t_icon} {total_perc:.2f}% ({total_net:.2f}€)"
    )


def get_performance() -> str:
    """Fetch prices for every holding and return the formatted performance string."""
    portfolio = load_portfolio()
    total_cost = 0
    current_total_value = 0
    yesterday_total_value = 0
    five_days_start_total_value = 0  # Trailing 5-day start value
    one_month_start_total_value = 0  # Trailing 1-month (30 days) start value
    ytd_start_total_value = 0  # Year-to-Date start value
    year_start_total_value = 0  # Trailing 1-year (365 days) start value

    # 1. Get the current EUR/USD exchange rate (e.g., 1.08)
    # We use the special ticker 'EURUSD=X'
    try:
        usd_eur_rate = 1 / yf.Ticker("EURUSD=X").fast_info['last_price']
    except Exception:
        usd_eur_rate = 0.92  # Manual fallback if the exchange rate fetch fails
        logger.warning("EUR/USD rate fetch failed, using fallback %.2f", usd_eur_rate, exc_info=True)

    # System "today", used only to size the history() fetch window below.
    # The actual reference dates (yesterday/5D/1M/YTD/1Y anchors) are
    # computed per-ticker from `effective_today` further down instead of
    # from this value directly — see the comment there for why.
    today = date.today()
    last_day_of_prev_year_hint = date(today.year - 1, 12, 31)
    five_days_ago_hint = today - timedelta(days=5)
    one_month_ago_hint = today - timedelta(days=30)
    one_year_ago_hint = today - timedelta(days=365)
    # Earliest date we need historical data for, so the 5D, 1M, YTD, and
    # 1-year reference prices can all be read from a single history() call.
    earliest_target_date = min(
        last_day_of_prev_year_hint, one_year_ago_hint, one_month_ago_hint, five_days_ago_hint
    )

    for symbol, lots in portfolio.items():
        try:
            ticker = yf.Ticker(symbol)
            qty = sum(shares for shares, cost, purchase_date in lots)
            ticker_total_cost = sum(shares * cost for shares, cost, purchase_date in lots)

            # Fetch one history window covering both reference dates (YTD
            # start and 1-year-ago), instead of one history() call per
            # date. Starts 7 days early so a valid trading day is found
            # even if the exact target date falls on a weekend/holiday.
            # keepna=True: without it, yfinance silently *drops* any row
            # where every OHLC+Volume field is null instead of returning it
            # with a NaN Close — confirmed live for a genuine mid-week
            # trading session (not a holiday) that Yahoo just hadn't
            # backfilled yet. A dropped row disappears from `hist`'s index
            # entirely, which would make `_n_trading_sessions_ago`'s
            # position-based counting (further down) silently skip that
            # session and land one day too far back — keepna=True keeps the
            # row (as NaN) so that counting stays accurate.
            hist = ticker.history(
                start=earliest_target_date - timedelta(days=7), end=today + timedelta(days=1), keepna=True
            )

            # Yahoo sometimes returns a row (the still-forming latest
            # session, or an as-yet-unbackfilled earlier one) with NaN OHLC
            # while Volume is already populated — confirmed live: the NaN
            # row's Volume matches fast_info's lastVolume exactly for the
            # still-forming case, so the bar just hasn't been finalized yet.
            # Filter those rows out before using `hist` for any "last known
            # close" lookup, so an incomplete session is never mistaken for
            # a real trading day.
            valid_hist = hist.dropna(subset=['Close'])
            if valid_hist.empty:
                raise ValueError(f"no valid closing prices for {symbol}")

            # Ticker's currency (e.g., 'EUR' or 'USD')
            currency = ticker.fast_info.get('currency', 'EUR')

            # Read current price from this same history window instead of a
            # separate fast_info call, matching fast_info's `last_price`
            # exactly when today's bar is finalized.
            today_bar_is_valid = not pd.isna(hist['Close'].iloc[-1])
            if today_bar_is_valid:
                current_price = hist['Close'].iloc[-1]
                # The session calendar's last entry *is* today here, so the
                # prior session is one step back, and "5 sessions ago" is
                # counted from today itself (n=5).
                prev_close_session_offset = 1
                five_days_session_offset = 5
            else:
                # Today's bar hasn't settled yet (NaN Close, see above).
                # Prefer fast_info's live quote for "current" — already
                # fetched for `currency` above, so this costs no extra
                # request. NOTE: must use `[...]`, not `.get(...)`:
                # FastInfo.get() only recognizes its camelCase key names
                # ('lastPrice'), and silently returns None for the
                # documented snake_case alias ('last_price') that
                # `__getitem__` accepts — confirmed against the real
                # yfinance API, not just its docs.
                try:
                    current_price = ticker.fast_info['last_price']
                    if pd.isna(current_price):
                        raise ValueError
                except Exception:
                    current_price = valid_hist['Close'].iloc[-1]
                # The incomplete/not-yet-backfilled session was already
                # excluded from the session calendar's trailing edge (see
                # _n_trading_sessions_ago), so its last entry is already the
                # last *complete* session — no extra step back needed.
                prev_close_session_offset = 0
                # "Today" (whose live price we're using above) isn't a
                # session in the calendar at all, so it only takes 4 more
                # steps back from its last entry to reach "5 sessions before
                # today" — one less than in the branch above.
                five_days_session_offset = 4

            # "Effective today": the most recent session Yahoo's data
            # actually reflects for this ticker. This can lag the raw
            # system date — either the exchange's timezone differs from
            # the system's, or (the common case here) Yahoo just hasn't
            # backfilled the latest completed session's Close yet (see the
            # NaN handling above). Anchoring every reference-date lookup to
            # this instead of system `today` keeps them aligned with
            # whichever price is being treated as "current" above.
            effective_today = hist.index[-1].date()
            five_days_ago = effective_today - timedelta(days=5)
            one_month_ago = effective_today - timedelta(days=30)
            one_year_ago = effective_today - timedelta(days=365)
            last_day_of_prev_year = date(effective_today.year - 1, 12, 31)

            # Fetch intraday (hourly) data once, used to refine both
            # yesterday's and 5D's reference prices below: Yahoo's own
            # figures anchor to the last intraday trade at/before a
            # session's edge, not always the official daily close
            # `_n_trading_sessions_ago` reads from daily bars — and Yahoo
            # occasionally has no daily bar at all for a session (a
            # genuine data gap, confirmed live for an ordinary mid-week
            # session, not a holiday) while still having hourly bars for
            # it, so this also serves as the fallback price source when a
            # session's daily close is missing entirely. This request is
            # small and short-range (a handful of days of hourly bars, not
            # the full 1M/YTD/1Y window), and both refinements below fall
            # back to the daily-derived price if it fails for any reason.
            try:
                hourly_hist = ticker.history(
                    start=today - timedelta(days=10), end=today + timedelta(days=1), interval="1h"
                )
            except Exception:
                hourly_hist = pd.DataFrame()
                logger.debug("hourly history fetch failed for %s, using daily close instead", symbol, exc_info=True)

            prev_close_date, prev_close = _n_trading_sessions_ago(
                hist, valid_hist, prev_close_session_offset, effective_today - timedelta(days=1), current_price
            )
            prev_close = _last_intraday_close(hourly_hist, prev_close_date, prev_close)

            # Prefer Yahoo's official previous-close (live quote endpoint)
            # over the chart-derived estimate above: even hourly-refined,
            # that estimate is the last *continuous-trading* print, not the
            # closing-auction price Yahoo's own "Day Change" is anchored
            # to — confirmed live, a multi-cent-per-share difference for
            # these instruments. This directly fixes 1D; it also improves
            # 5D/1M/YTD/1Y's fallback value below (used only when a
            # ticker's history is too short to cover the full window), so
            # there's no reason to keep the less accurate one around.
            live_prev_close = _fetch_regular_market_previous_close(ticker, symbol)
            if live_prev_close is not None:
                prev_close = live_prev_close
            else:
                logger.debug("live previous-close fetch failed for %s, using chart-derived value", symbol)

            five_days_start_date, five_days_start_price = _n_trading_sessions_ago(
                hist, valid_hist, five_days_session_offset, five_days_ago, prev_close
            )
            five_days_start_price = _last_intraday_close(hourly_hist, five_days_start_date, five_days_start_price)

            one_month_start_price = _closing_price_on_or_before(
                valid_hist, one_month_ago, prev_close, strictly_before=True
            )
            ytd_start_price = _closing_price_on_or_before(
                valid_hist, last_day_of_prev_year, prev_close, strictly_before=True
            )
            year_start_price = _closing_price_on_or_before(
                valid_hist, one_year_ago, prev_close, strictly_before=True
            )

            # 2. If the data is in USD, convert it to EUR. Lot costs are
            # never converted: they're what you actually paid, already in EUR.
            if currency == 'USD':
                current_price *= usd_eur_rate
                prev_close *= usd_eur_rate
                five_days_start_price *= usd_eur_rate
                one_month_start_price *= usd_eur_rate
                ytd_start_price *= usd_eur_rate
                year_start_price *= usd_eur_rate

            total_cost += ticker_total_cost
            current_total_value += qty * current_price
            yesterday_total_value += _value_as_of(lots, prev_close_date, prev_close)
            five_days_start_total_value += _value_as_of(lots, five_days_start_date, five_days_start_price)
            one_month_start_total_value += _value_as_of(lots, one_month_ago, one_month_start_price)
            ytd_start_total_value += _value_as_of(lots, last_day_of_prev_year, ytd_start_price)
            year_start_total_value += _value_as_of(lots, one_year_ago, year_start_price)
        except Exception:
            logger.warning("skipping %s due to an error", symbol, exc_info=True)
            continue

    return format_performance(
        total_cost,
        current_total_value,
        yesterday_total_value,
        five_days_start_total_value,
        one_month_start_total_value,
        ytd_start_total_value,
        year_start_total_value,
    )


def main() -> None:
    """Print the performance ticker line, or an error message on failure."""
    try:
        print(get_performance())
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":  # pragma: no cover
    main()