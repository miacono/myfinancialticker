# My Financial Ticker

A simple Python script to monitor the performance of an investment portfolio directly from your terminal.

## Features

- Fetches real-time stock and ETF prices using the `yfinance` library.
- Calculates the daily and total profit/loss of the portfolio.
- Supports assets listed in EUR and USD, with automatic currency conversion.
- Portfolio configuration is kept separate from the code in a `portfolio.json` file for easy customization.
- Compact and easy-to-read output, ideal for integration into status bars or system scripts.

## Prerequisites

- Python 3.9+ (required by the pinned `pandas` version)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/myfinancialticker.git
    cd myfinancialticker
    ```

2.  **Install the dependencies:**
    It is recommended to create a virtual environment before proceeding.
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

To use the script, you need to create a `portfolio.json` file in the project's root directory. This file will hold your portfolio data.

1.  Create a file named `portfolio.json`.
2.  Add your assets as a list of purchase lots per ticker, each lot being
    `[QUANTITY, PRICE_PAID, "PURCHASE_DATE"]` (date in ISO `YYYY-MM-DD`
    format):

    ```json
    {
        "TICKER_1": [
            [QUANTITY, PRICE_PAID, "PURCHASE_DATE"]
        ],
        "TICKER_2": [
            [QUANTITY, PRICE_PAID, "PURCHASE_DATE"],
            [QUANTITY, PRICE_PAID, "PURCHASE_DATE"]
        ]
    }
    ```

    Recording each purchase separately (instead of a single average cost)
    lets the script correctly value a period like `5D`/`1M`/`YTD`/`1Y` even
    when you bought more shares partway through it: shares you already
    owned at the start of the period are priced at that day's market price,
    while shares bought during the period are valued at what you actually
    paid for them — the same approach Yahoo Finance itself uses, and it's
    also why `1Y` and `T` (total) end up equal for a position you've held
    for less than a year.

    **Example:**
    ```json
    {
        "SWDA.MI": [
            [15, 104.92, "2025-08-26"],
            [1, 108.70, "2025-10-13"],
            [1, 112.24, "2025-11-12"]
        ],
        "GOOGL": [
            [5, 150.75, "2024-03-01"]
        ]
    }
    ```
    > **Note:** The `portfolio.json` file is already included in `.gitignore` to protect your personal data.

## Usage

Once the portfolio is configured, run the script from your terminal:

```bash
python myfinancialticker.py
```

### Sample Output

The output shows daily performance (percentage and absolute variance from the previous close), trailing 5-day performance, trailing 1-month performance, year-to-date (YTD) performance, trailing 1-year performance, and total performance (percentage and absolute profit/loss), using Yahoo Finance's own labels (`1D`, `5D`, `1M`, `YTD`, `1Y`, `T`).

```
1D: ▲ 0.45% (+15.30€) | 5D: ▲ 1.20% (+40.00€) | 1M: ▲ 3.10% (+100.00€) | YTD: ▲ 5.80% (195.50€) | 1Y: ▲ 8.10% (250.00€) | T: ▲ 12.30% (450.00€)
```

## Development

Install the development dependencies (adds `pytest` and `pytest-cov` on top of the runtime requirements) and run the test suite:

```bash
pip install -r requirements-dev.txt
pytest
```

`yfinance`/`yf.Ticker` is mocked throughout, so the tests don't hit the network or depend on live market data. Every run also measures coverage and fails if it drops below 95% (configured in `pyproject.toml`); the suite currently reaches 100%.