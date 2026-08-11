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


def load_portfolio(filename: str = "portfolio.json") -> dict[str, list[float]]:
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


def format_performance(
    total_cost: float,
    current_total_value: float,
    yesterday_total_value: float,
    ytd_start_total_value: float,
    year_start_total_value: float,
) -> str:
    """Compute daily/YTD/1Y/total performance and format the ticker string.

    Pure function (no I/O): all inputs are already-aggregated portfolio
    totals in the same currency (EUR), which makes it testable without
    mocking yfinance.
    """
    if total_cost == 0:
        return "ETF: Error"

    daily_net = current_total_value - yesterday_total_value
    daily_perc = (daily_net / yesterday_total_value) * 100 if yesterday_total_value != 0 else 0
    ytd_net = current_total_value - ytd_start_total_value
    ytd_perc = (ytd_net / ytd_start_total_value) * 100 if ytd_start_total_value != 0 else 0
    year_net = current_total_value - year_start_total_value
    year_perc = (year_net / year_start_total_value) * 100 if year_start_total_value != 0 else 0
    total_net = current_total_value - total_cost
    total_perc = (total_net / total_cost) * 100 if total_cost != 0 else 0

    d_icon = "▲" if daily_net >= 0 else "▼"
    ytd_icon = "▲" if ytd_net >= 0 else "▼"
    y_icon = "▲" if year_net >= 0 else "▼"
    t_icon = "▲" if total_net >= 0 else "▼"

    return (
        f"1D: {d_icon} {daily_perc:.2f}% ({daily_net:+.2f}€) | "
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
    last_day_of_prev_year = date(today.year - 1, 12, 31)
    # Reference date for the trailing 1-year performance (365 days ago)
    one_year_ago = today - timedelta(days=365)
    # Earliest date we need historical data for, so both the YTD and the
    # 1-year reference price can be read from a single history() call.
    earliest_target_date = min(last_day_of_prev_year, one_year_ago)

    for symbol, holding in portfolio.items():
        try:
            ticker = yf.Ticker(symbol)
            qty, cost = holding  # Unpack quantity and average purchase cost

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
            # carry. This keeps requests at 2 per ticker instead of 3
            # (fast_info alone costs 2 requests; history() costs 1).
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2] if len(hist) >= 2 else current_price

            # Ticker's currency (e.g., 'EUR' or 'USD')
            currency = ticker.fast_info.get('currency', 'EUR')

            ytd_start_price = _closing_price_on_or_before(hist, last_day_of_prev_year, prev_close)
            year_start_price = _closing_price_on_or_before(hist, one_year_ago, prev_close)

            # 2. If the data is in USD, convert it to EUR
            if currency == 'USD':
                current_price *= usd_eur_rate
                prev_close *= usd_eur_rate
                ytd_start_price *= usd_eur_rate
                year_start_price *= usd_eur_rate

            total_cost += qty * cost
            current_total_value += qty * current_price
            yesterday_total_value += qty * prev_close
            ytd_start_total_value += qty * ytd_start_price
            year_start_total_value += qty * year_start_price
        except Exception:
            continue

    return format_performance(
        total_cost,
        current_total_value,
        yesterday_total_value,
        ytd_start_total_value,
        year_start_total_value,
    )


if __name__ == "__main__":
    try:
        print(get_performance())
    except Exception as e:
        print(f"Error: {e}")