import yfinance as yf
import pandas as pd
import warnings
import json
import sys
import os
from datetime import date, timedelta

# Silence noisy library warnings from yfinance/pandas; real errors still
# propagate as exceptions and are not affected by this filter.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


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


def _closing_price_on_or_before(hist: pd.DataFrame, target_date: date, fallback: float) -> float:
    """Return the last closing price in `hist` on or before `target_date`.

    Falls back to `fallback` if `hist` is empty or has no rows on or
    before `target_date`.
    """
    if hist.empty:
        return fallback
    prior_rows = hist[hist.index.date <= target_date]
    if prior_rows.empty:
        return fallback
    return prior_rows['Close'].iloc[-1]


def _n_trading_sessions_ago(
    hist: pd.DataFrame, n: int, fallback_date: date, fallback_price: float
) -> tuple[date, float]:
    """Return the (date, closing price) of the trading session `n` sessions before the most recent row in `hist`.

    Falls back to `(fallback_date, fallback_price)` if `hist` has `n` rows
    or fewer. Used for `5D`: Yahoo Finance counts trading sessions, not
    calendar days, and a plain 5-calendar-day lookback often only spans
    3-4 actual sessions once a weekend is in the window, understating a
    period this short far more than it does the longer ones.
    """
    if len(hist) <= n:
        return fallback_date, fallback_price
    row = hist.iloc[-(n + 1)]
    return row.name.date(), row['Close']


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


def _value_as_of(lots: list[list], target_date: date, market_price: float) -> float:
    """Value a ticker's lots as they stood on `target_date`.

    Lots already purchased on or before `target_date` are valued at
    `market_price` (what they were actually worth then). Lots purchased
    after `target_date` didn't exist yet as of that date, so they're valued
    at their own purchase cost instead — otherwise a period would price
    shares you didn't own yet using a today's-quantity-times-past-price
    shortcut, overstating or understating how much the portfolio was
    really worth at that point in time.
    """
    total = 0.0
    for shares, cost, purchase_date in lots:
        if date.fromisoformat(purchase_date) <= target_date:
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

    # Get the last trading day of the previous year
    today = date.today()
    yesterday = today - timedelta(days=1)
    last_day_of_prev_year = date(today.year - 1, 12, 31)
    # Calendar-day approximation of the trailing 5-day reference date. Only
    # used to size the history() fetch window and as a fallback when a
    # ticker's history is too short for _n_trading_sessions_ago to count
    # back 5 actual sessions; the real 5D reference is trading-session
    # based (see _n_trading_sessions_ago).
    five_days_ago = today - timedelta(days=5)
    # Reference date for the trailing 1-month performance (30 days ago)
    one_month_ago = today - timedelta(days=30)
    # Reference date for the trailing 1-year performance (365 days ago)
    one_year_ago = today - timedelta(days=365)
    # Earliest date we need historical data for, so the 5D, 1M, YTD, and
    # 1-year reference prices can all be read from a single history() call.
    earliest_target_date = min(last_day_of_prev_year, one_year_ago, one_month_ago, five_days_ago)

    for symbol, lots in portfolio.items():
        try:
            ticker = yf.Ticker(symbol)
            qty = sum(shares for shares, cost, purchase_date in lots)
            ticker_total_cost = sum(shares * cost for shares, cost, purchase_date in lots)

            # Fetch one history window covering both reference dates (YTD
            # start and 1-year-ago), instead of one history() call per
            # date. Starts 7 days early so a valid trading day is found
            # even if the exact target date falls on a weekend/holiday.
            hist = ticker.history(start=earliest_target_date - timedelta(days=7), end=today + timedelta(days=1))

            # Read current price and previous close from this same history
            # window instead of a separate fast_info call: the last row is
            # today's (still-forming) session and the second-to-last row is
            # the last completed session, matching fast_info's `last_price`
            # and `regular_market_previous_close` exactly. fast_info is only
            # used below for `currency`, which the history response doesn't
            # carry. This keeps requests at 2 per ticker for `1M`/`YTD`/`1Y`
            # (fast_info alone costs 2 requests; history() costs 1); `5D`
            # below adds a 3rd, smaller request for hourly data.
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2] if len(hist) >= 2 else current_price

            # Ticker's currency (e.g., 'EUR' or 'USD')
            currency = ticker.fast_info.get('currency', 'EUR')

            five_days_start_date, five_days_start_price = _n_trading_sessions_ago(
                hist, 5, five_days_ago, prev_close
            )
            # Refine the 5D reference price with an intraday (hourly) fetch:
            # Yahoo's own `5D` anchors to the last intraday trade before the
            # window starts, which for low-volatility instruments can differ
            # from the official daily close above by more than is
            # proportionate for a period this short. This 3rd request is a
            # small, short-range one (a handful of days of hourly bars, not
            # the full 1M/YTD/1Y window), and falls back to the daily-close
            # price above if it fails for any reason.
            try:
                hourly_hist = ticker.history(
                    start=today - timedelta(days=10), end=today + timedelta(days=1), interval="1h"
                )
            except Exception:
                hourly_hist = pd.DataFrame()
            five_days_start_price = _last_intraday_close(hourly_hist, five_days_start_date, five_days_start_price)

            one_month_start_price = _closing_price_on_or_before(hist, one_month_ago, prev_close)
            ytd_start_price = _closing_price_on_or_before(hist, last_day_of_prev_year, prev_close)
            year_start_price = _closing_price_on_or_before(hist, one_year_ago, prev_close)

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
            yesterday_total_value += _value_as_of(lots, yesterday, prev_close)
            five_days_start_total_value += _value_as_of(lots, five_days_start_date, five_days_start_price)
            one_month_start_total_value += _value_as_of(lots, one_month_ago, one_month_start_price)
            ytd_start_total_value += _value_as_of(lots, last_day_of_prev_year, ytd_start_price)
            year_start_total_value += _value_as_of(lots, one_year_ago, year_start_price)
        except Exception:
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