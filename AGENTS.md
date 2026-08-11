# AGENTS.md

Guidelines for any AI agent (Claude, Gemini, or other) working in this repository.

## Overview

`myfinancialticker` is a small, single-script Python tool that prints a compact
one-line summary of an investment portfolio's performance (daily, year-to-date,
and total profit/loss). It's designed to be embedded in terminal status bars
(xbar, polybar, i3blocks, etc.).

## Language

All code comments, docstrings, and project documentation files (`README.md`,
`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, etc.) must be written in **English**,
regardless of the language used in the conversation with the user. Keep this
in mind when adding or editing any comment or doc file.

## File structure

- `myfinancialticker.py` — the entire application logic (see below).
- `conftest.py` — makes `myfinancialticker` importable from `tests/`
  regardless of how pytest is invoked.
- `tests/test_myfinancialticker.py` — pytest suite for `load_portfolio`,
  `format_performance`, and `_closing_price_on_or_before`. Network-free.
- `portfolio.json.example` — example portfolio config showing the expected format.
- `portfolio.json` — the user's real portfolio data. **Gitignored** — contains
  personal financial data, never commit it.
- `README.md` — user-facing documentation (installation, configuration, usage).
- `requirements.txt` — pinned runtime dependencies (`yfinance`, `pandas`).
- `requirements-dev.txt` — runtime dependencies plus `pytest`, for running the
  test suite.
- `venv/` — local virtualenv. Not part of the project source; ignore it when
  exploring or editing code, and never commit it.

## How it works

`myfinancialticker.py` has four functions:

- `load_portfolio(filename="portfolio.json")` — loads the portfolio JSON,
  resolving the path relative to the script's own location (not the current
  working directory). Exits via `sys.exit` with a message on missing file or
  invalid JSON.

- `_closing_price_on_or_before(hist, target_date, fallback)` — pure helper
  that returns the last closing price in an already-fetched history
  `DataFrame` on or before `target_date`, or `fallback` if none is found.
  No I/O, so it's directly unit-testable.

- `format_performance(total_cost, current_total_value, yesterday_total_value,
  ytd_start_total_value, year_start_total_value)` — pure function (no I/O)
  that computes daily, YTD, trailing 1-year, and total performance
  (percentage and absolute € value) from already-aggregated EUR totals, and
  returns a single formatted string using Yahoo Finance's own labels, in
  this order, with ▲/▼ icons, e.g.:
  `1D: ▲ 0.45% (+15.30€) | YTD: ▲ 5.80% (195.50€) | 1Y: ▲ 8.10% (250.00€) | T: ▲ 12.30% (450.00€)`

  - `1D` = daily change vs. previous close
  - `YTD` = year-to-date change (since Dec 31 of previous year)
  - `1Y` = trailing 1-year change (365 days ago vs. now)
  - `T` = total change vs. average purchase cost

  Returns `"ETF: Error"` if `total_cost` is 0 (empty/unreadable portfolio).

- `get_performance()` — the I/O-heavy orchestration:
  1. Fetches the EUR/USD exchange rate via `yf.Ticker("EURUSD=X")`, falling
     back to a hardcoded `0.92` if the fetch fails.
  2. Determines the last trading day of the previous year (for YTD) and the
     date 365 days ago (for the trailing 1-year metric).
  3. For each ticker in the portfolio (`{"TICKER": [quantity, avg_cost]}`):
     - Fetches current price and previous close via `fast_info`.
     - Fetches **one** `history()` window per ticker that covers both
       reference dates (YTD start and 1-year-ago), then reads both prices
       out of it via `_closing_price_on_or_before` — this is a deliberate
       choice to keep network requests down (2 requests per ticker instead
       of 3) after real rate-limiting (HTTP 429) was observed from Yahoo
       Finance during development. Don't reintroduce a second `history()`
       call per ticker.
     - Converts USD-denominated prices to EUR using the fetched rate.
     - Accumulates total cost, current value, previous-day value, YTD-start
       value, and 1-year-ago value.
     - Any per-ticker error is silently skipped (`except Exception: continue`)
       so one bad/delisted ticker doesn't break the whole output.
  4. Calls `format_performance(...)` with the accumulated totals and returns
     its result.

`__main__` calls `get_performance()` and prints the result, wrapped in a
generic try/except so the script never crashes with a traceback (important
since it runs inside status bar widgets).

## Portfolio data format

`portfolio.json` maps ticker symbols (Yahoo Finance format, e.g. `SWDA.MI`,
`GOOGL`) to a `[quantity, average_purchase_price]` pair:

```json
{
    "SWDA.MI": [19, 106.32],
    "GOOGL": [5, 150.75]
}
```

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
  (HTTP 429) have been observed in practice; `get_performance()` is written
  to make at most 2 requests per ticker (`fast_info` + one `history()` call).
  Prefer adding logic to the existing pure helpers (`_closing_price_on_or_before`,
  `format_performance`) over adding new network calls.

## Useful commands

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python myfinancialticker.py
```

Run the test suite (no network access required):

```bash
pip install -r requirements-dev.txt
pytest
```

There is no linter configured. The pure logic (`format_performance`,
`_closing_price_on_or_before`, `load_portfolio`) is covered by
`tests/test_myfinancialticker.py`; the network-dependent orchestration in
`get_performance()` is not covered by automated tests and should be verified
by running the script directly.

## What NOT to do

- Never commit the real `portfolio.json` (personal financial data).
- Never commit `venv/`.
- Don't invent new config files or change the `portfolio.json` schema without
  updating `README.md` and `portfolio.json.example` to match.
