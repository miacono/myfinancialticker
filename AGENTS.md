# AGENTS.md

Guidelines for any AI agent (Claude, Gemini, or other) working in this repository.

## Overview

`myfinancialticker` is a small, single-script Python tool that prints a compact
one-line summary of an investment portfolio's performance (daily, year-to-date,
and total profit/loss). It's designed to be embedded in terminal status bars
(xbar, polybar, i3blocks, etc.).

## File structure

- `myfinancialticker.py` — the entire application logic (see below).
- `portfolio.json.example` — example portfolio config showing the expected format.
- `portfolio.json` — the user's real portfolio data. **Gitignored** — contains
  personal financial data, never commit it.
- `README.md` — user-facing documentation (installation, configuration, usage).
- `requirements.txt` — pinned dependencies (`yfinance`, `pandas`).
- `venv/` — local virtualenv. Not part of the project source; ignore it when
  exploring or editing code, and never commit it.

## How it works

`myfinancialticker.py` has two functions:

- `load_portfolio(filename="portfolio.json")` — loads the portfolio JSON,
  resolving the path relative to the script's own location (not the current
  working directory). Exits via `sys.exit` with a message on missing file or
  invalid JSON.

- `get_performance()` — the core logic:
  1. Fetches the EUR/USD exchange rate via `yf.Ticker("EURUSD=X")`, falling
     back to a hardcoded `0.92` if the fetch fails.
  2. Determines the last trading day of the previous year (for YTD).
  3. For each ticker in the portfolio (`{"TICKER": [quantity, avg_cost]}`):
     - Fetches current price and previous close via `fast_info`.
     - Fetches historical data to find the closing price at year start,
       looking back up to 7 days to land on a valid trading day.
     - Converts USD-denominated prices to EUR using the fetched rate.
     - Accumulates total cost, current value, previous-day value, and
       year-start value.
     - Any per-ticker error is silently skipped (`except Exception: continue`)
       so one bad/delisted ticker doesn't break the whole output.
  4. Computes daily, YTD, and total performance (percentage and absolute € value)
     and returns a single formatted string with ▲/▼ icons, e.g.:
     `D: ▲ 0.45% (+15.30€) | Y: ▲ 5.80% (195.50€) | T: ▲ 12.30% (450.00€)`

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
- **No automated tests exist** in this repo currently.

## Useful commands

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python myfinancialticker.py
```

There is no lint or test suite configured — verify changes by running the
script directly and checking the output format.

## What NOT to do

- Never commit the real `portfolio.json` (personal financial data).
- Never commit `venv/`.
- Don't invent new config files or change the `portfolio.json` schema without
  updating `README.md` and `portfolio.json.example` to match.
