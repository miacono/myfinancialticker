# AGENTS.md

Guidelines for any AI agent (Claude, Gemini, or other) working in this repository.

## Overview

`myfinancialticker` is a small, single-script Python tool that prints a compact
one-line summary of an investment portfolio's performance (daily, 5-day,
1-month, year-to-date, trailing 1-year, and total profit/loss). It's designed
to be embedded in terminal status bars (xbar, polybar, i3blocks, etc.).

## Git workflow

- **Always commit atomically.** Each commit should contain one logical,
  self-contained change (one fix, one refactor step, one doc update, etc.)
  with a message describing just that change. Don't bundle unrelated
  changes into a single commit, even within the same task.
- **Never push without asking first**, even if a previous push in the same
  session was already approved — always confirm again before running
  `git push`. Committing locally does not require asking.

## Language

All code comments, docstrings, and project documentation files (`README.md`,
`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, etc.) must be written in **English**,
regardless of the language used in the conversation with the user. Keep this
in mind when adding or editing any comment or doc file.

## File structure

- `myfinancialticker.py` — the entire application logic (see below).
- `conftest.py` — makes `myfinancialticker` importable from `tests/`
  regardless of how pytest is invoked.
- `tests/test_myfinancialticker.py` — pytest suite covering every function,
  including `get_performance()` and `main()` via a `_FakeTicker` stand-in for
  `yf.Ticker`. Network-free; 100% line and branch coverage.
- `pyproject.toml` — pytest/coverage config: every `pytest` run measures
  coverage and fails if it drops below 95%.
- `portfolio.json.example` — example portfolio config showing the expected format.
- `portfolio.json` — the user's real portfolio data. **Gitignored** — contains
  personal financial data, never commit it.
- `README.md` — user-facing documentation (installation, configuration, usage).
- `requirements.txt` — pinned runtime dependencies (`yfinance`, `pandas`).
- `requirements-dev.txt` — runtime dependencies plus `pytest`/`pytest-cov`,
  for running the test suite with coverage.
- `venv/` — local virtualenv. Not part of the project source; ignore it when
  exploring or editing code, and never commit it.

## How it works

`myfinancialticker.py` has eight functions:

- `load_portfolio(filename="portfolio.json")` — loads the portfolio JSON,
  resolving the path relative to the script's own location (not the current
  working directory). Exits via `sys.exit` with a message on missing file or
  invalid JSON.

- `_closing_price_on_or_before(hist, target_date, fallback)` — pure helper
  that returns the last closing price in an already-fetched history
  `DataFrame` on or before `target_date`, or `fallback` if none is found.
  No I/O, so it's directly unit-testable. Used for `1M`/`YTD`/`1Y`, where a
  calendar-date lookback is an accurate enough approximation of Yahoo's own
  figures (verified against real output — see below).

- `_n_trading_sessions_ago(hist, n, fallback_date, fallback_price)` — pure
  helper that returns the `(date, closing price)` of the trading session
  `n` sessions before the most recent row in `hist`, or the fallback pair
  if there aren't enough rows. Used only for `5D`: a calendar 5-day
  lookback often only spans 3-4 real trading sessions once a weekend falls
  inside it, which — unlike for the longer periods — materially
  understates a window this short. No I/O, directly unit-testable.

- `_last_intraday_close(hourly_hist, target_date, fallback)` — pure helper
  that returns the last hourly closing price recorded on `target_date`, or
  `fallback` if `hourly_hist` has no rows on that date. Used to refine the
  `5D` reference price found above: Yahoo's own figure is anchored to the
  last *intraday* trade before the window starts, not the end-of-day
  official closing price, and for low-volatility instruments (e.g. a cash
  ETF) those two can differ enough to matter over a period this short.
  Confirmed by reading Yahoo's own portfolio-performance-chart API
  response (`portfolio-timeseries-api/v2/portfolio/performance/chart`) and
  matching its `baseline` field to the cent. No I/O, directly unit-testable.

- `_value_as_of(lots, target_date, market_price)` — pure helper that values
  a ticker's lots (`[[shares, cost, purchase_date], ...]`) as of
  `target_date`: lots already purchased by then are valued at
  `market_price`, lots purchased afterward are valued at their own cost
  (they didn't exist as a holding on `target_date`, so pricing them at a
  historical market price would misstate what the portfolio was actually
  worth then). No I/O, directly unit-testable.

- `format_performance(total_cost, current_total_value, yesterday_total_value,
  five_days_start_total_value, one_month_start_total_value,
  ytd_start_total_value, year_start_total_value)` — pure function (no I/O)
  that computes daily, 5-day, 1-month, YTD, trailing 1-year, and total
  performance (percentage and absolute € value) from already-aggregated EUR
  totals, and returns a single formatted string using Yahoo Finance's own
  labels, in this order, with ▲/▼ icons, e.g.:
  `1D: ▲ 0.45% (+15.30€) | 5D: ▲ 1.20% (+40.00€) | 1M: ▲ 3.10% (+100.00€) | YTD: ▲ 5.80% (195.50€) | 1Y: ▲ 8.10% (250.00€) | T: ▲ 12.30% (450.00€)`

  - `1D` = daily change vs. previous close
  - `5D` = change over the trailing 5 *trading* days (see `_n_trading_sessions_ago`)
  - `1M` = change over the trailing 1 month (30 calendar days)
  - `YTD` = year-to-date change (since Dec 31 of previous year)
  - `1Y` = trailing 1-year change (365 days ago vs. now)
  - `T` = total change vs. average purchase cost

  Returns `"ETF: Error"` if `total_cost` is 0 (empty/unreadable portfolio).

- `get_performance()` — the I/O-heavy orchestration:
  1. Fetches the EUR/USD exchange rate via `yf.Ticker("EURUSD=X")`, falling
     back to a hardcoded `0.92` if the fetch fails.
  2. Determines the last trading day of the previous year (for YTD) and the
     dates 5 days ago, 30 days ago, and 365 days ago (for the 5D, 1M, and
     trailing 1-year metrics).
  3. For each ticker in the portfolio (`{"TICKER": [[shares, cost,
     purchase_date], ...]}`), makes **3** requests to Yahoo Finance:
     - **One** daily `history()` call per ticker, with a window that covers
       all reference dates (5D, 1M, YTD start, and 1-year-ago). Current price
       and previous close are read from this same DataFrame's last two rows
       (`hist['Close'].iloc[-1]`/`[-2]`) — verified to be byte-identical to
       `fast_info`'s `last_price`/`regular_market_previous_close`. `1M`/`YTD`/
       `1Y` reference prices come from `_closing_price_on_or_before`; `5D`'s
       reference *date* comes from `_n_trading_sessions_ago` instead (see
       above for why).
     - **One** `fast_info` access, used only for `currency` — `fast_info`
       alone costs 2 requests when `last_price`/`regular_market_previous_close`
       are also read, so those fields are deliberately *not* read from it
       anymore.
     - **One** short-range `history(interval="1h")` call, used only to
       refine `5D`'s reference *price* via `_last_intraday_close` once its
       date is known (see above). Wrapped in its own `try`/`except`, falling
       back to the daily-close price on failure, so a hiccup here degrades
       `5D`'s precision rather than dropping the ticker from every metric.
     - Converts USD-denominated prices to EUR using the fetched rate. Lot
       costs are never converted — they're what was actually paid, already
       in EUR.
     - Values every lookback window (yesterday, 5D, 1M, YTD, 1Y) via
       `_value_as_of(lots, target_date, market_price)` rather than a flat
       `current_qty * historical_price`. This matters whenever the position
       size changed within a window: pricing today's full quantity against
       a past date overstates or understates what the portfolio was
       actually worth back then. It was diagnosed by comparing output
       against Yahoo Finance's own portfolio "Rendimento" view — for a
       position accumulated via several purchases over less than a year,
       Yahoo's `1Y` figure exactly matched `T` (both effectively clamped to
       the since-first-purchase return), and its `YTD` baseline matched
       `(quantity held at YTD start × YTD-start price) + (cost of shares
       bought since)` to the cent. `_value_as_of` generalizes that: lots
       already held at a target date are priced at that date's market
       price, lots bought after it are valued at their own cost. Combined
       with the trading-session-based `5D` date and the intraday-refined
       `5D` price above, real output now matches Yahoo's own figures for
       `1D`/`5D`/`1M`/`YTD`/`1Y`/`T` exactly — verified against a real
       portfolio's actual figures, including by reading Yahoo's own
       portfolio-performance API response directly.
     - Accumulates total cost, current value, previous-day value, 5-day-ago
       value, 1-month-ago value, YTD-start value, and 1-year-ago value.
     - Any per-ticker error is silently skipped (`except Exception: continue`)
       so one bad/delisted ticker doesn't break the whole output.
  4. Calls `format_performance(...)` with the accumulated totals and returns
     its result.

  This design was reached after real rate-limiting (HTTP 429) was observed
  from Yahoo Finance during development, and after tracing actual HTTP calls
  (via `curl_cffi`, which `yfinance` uses under the hood) to measure the true
  request count of each approach. Two findings from that investigation:
  - A true single-request multi-ticker batch is **not possible**: Yahoo's
    chart endpoint (`v8/finance/chart/<SYMBOL>`), which both `history()` and
    `yf.download()` rely on, only accepts one symbol per request. Confirmed
    by tracing `yf.download()` itself, which just issues one request per
    ticker under the hood — it doesn't reduce request count, only adds
    threading. Don't attempt to route through `yf.download()`/`yf.Tickers()`
    expecting a real multi-ticker batch; there isn't one on this API.
  - `fast_info` internally makes a separate request for `last_price`/
    `regular_market_previous_close` beyond its basic per-ticker request —
    hence deriving those two fields from `history()` instead removes a
    whole request per ticker. Don't add back a `fast_info` access for
    `last_price`/`regular_market_previous_close`.

- `main()` — calls `get_performance()` and prints the result, wrapped in a
  generic try/except so the script never crashes with a traceback (important
  since it runs inside status bar widgets). Called from the
  `if __name__ == "__main__":` guard, which is excluded from coverage
  (`# pragma: no cover`) since it contains no logic beyond that call —
  `main()` itself is covered directly in tests.

## Portfolio data format

`portfolio.json` maps ticker symbols (Yahoo Finance format, e.g. `SWDA.MI`,
`GOOGL`) to a **list of purchase lots**, each lot being
`[shares, price_paid, purchase_date]` (date as an ISO `YYYY-MM-DD` string):

```json
{
    "SWDA.MI": [
        [15, 104.92, "2025-08-26"],
        [1, 108.70, "2025-10-13"]
    ],
    "GOOGL": [
        [5, 150.75, "2024-03-01"]
    ]
}
```

Every lot needs all three fields — there's no single-lot/average-cost
shorthand. Recording each purchase separately (instead of one aggregate
quantity + average cost) is what lets `_value_as_of` price `5D`/`1M`/`YTD`/
`1Y` correctly when the position size changed partway through the window —
see "How it works" above.

## Conventions and constraints

- **Keep it minimal.** This is intentionally a single-file script. Don't add
  new dependencies, frameworks, or split it into modules unless the user
  explicitly asks for it.
- **Output must stay a compact single line** — it's rendered inside status bars
  with limited space. Don't make the output multi-line or verbose.
- **Error handling is deliberately permissive** (never crash, silently skip
  broken tickers) but currently has no logging at all. This is a known
  weak spot, not a pattern to blindly extend — if you touch error handling,
  preserve the "never crash" guarantee but feel free to improve visibility
  (e.g. optional logging) rather than copying the silent `except: continue`
  everywhere.
- **The EUR/USD fallback rate (`0.92`) is hardcoded.** If you change or
  parameterize it, call that out explicitly since it directly affects reported
  values when the live rate fetch fails.
- **Keep network calls per ticker to a minimum.** Yahoo Finance rate-limits
  (HTTP 429) have been observed in practice; `get_performance()` makes 3
  requests per ticker (daily `history()`, `fast_info` for `currency`, and a
  short-range hourly `history()` for `5D` precision — see "How it works").
  The 3rd request was added deliberately, as a known, accepted trade-off
  for matching Yahoo's `5D` figure exactly; don't add further requests
  without calling out the same trade-off explicitly. Prefer adding logic to
  the existing pure helpers (`_closing_price_on_or_before`,
  `_n_trading_sessions_ago`, `_last_intraday_close`, `_value_as_of`,
  `format_performance`) over adding new network calls.

## Useful commands

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python myfinancialticker.py
```

Run the test suite (no network access required — `yf.Ticker` is mocked via
`_FakeTicker` in `tests/test_myfinancialticker.py`, including for
`get_performance()` and `main()`):

```bash
pip install -r requirements-dev.txt
pytest
```

Every run measures coverage and fails if it drops below 95% (see
`pyproject.toml`); the suite currently reaches 100%. There is no linter
configured. When adding logic to `get_performance()`, extend the
`_FakeTicker`-based tests rather than skipping coverage for it — real
Yahoo Finance calls should never run in the test suite.

## What NOT to do

- Never commit the real `portfolio.json` (personal financial data).
- Never commit `venv/`.
- Don't invent new config files or change the `portfolio.json` schema without
  updating `README.md` and `portfolio.json.example` to match.
