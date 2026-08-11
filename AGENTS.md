# AGENTS.md

Guidelines for any AI agent (Claude, Gemini, or other) working in this repository.

## Overview

`myfinancialticker` is a small, single-script Python tool that prints a compact
one-line summary of an investment portfolio's performance (daily, year-to-date,
and total profit/loss). It's designed to be embedded in terminal status bars
(xbar, polybar, i3blocks, etc.).

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

`myfinancialticker.py` has five functions:

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
  3. For each ticker in the portfolio (`{"TICKER": [quantity, avg_cost]}`),
     makes exactly **2** requests to Yahoo Finance:
     - **One** `history()` call per ticker, with a window that covers both
       reference dates (YTD start and 1-year-ago). Current price and
       previous close are read from this same DataFrame's last two rows
       (`hist['Close'].iloc[-1]`/`[-2]`) — verified to be byte-identical to
       `fast_info`'s `last_price`/`regular_market_previous_close`. YTD/1Y
       reference prices are read from it via `_closing_price_on_or_before`.
     - **One** `fast_info` access, used only for `currency` — `fast_info`
       alone costs 2 requests when `last_price`/`regular_market_previous_close`
       are also read, so those fields are deliberately *not* read from it
       anymore.
     - Converts USD-denominated prices to EUR using the fetched rate.
     - Accumulates total cost, current value, previous-day value, YTD-start
       value, and 1-year-ago value.
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
  to make exactly 2 requests per ticker (one `history()` call, one
  `fast_info` access used only for `currency`). See "How it works" above for
  why this is the floor with the current public `yfinance` API. Prefer
  adding logic to the existing pure helpers (`_closing_price_on_or_before`,
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
