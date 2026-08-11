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
2.  Add your assets using the following JSON format:

    ```json
    {
        "TICKER_1": [QUANTITY, AVERAGE_PURCHASE_PRICE],
        "TICKER_2": [QUANTITY, AVERAGE_PURCHASE_PRICE]
    }
    ```

    **Example:**
    ```json
    {
        "SWDA.MI": [19, 106.32],
        "VUAA.MI": [1, 107.68],
        "GOOGL": [5, 150.75]
    }
    ```
    > **Note:** The `portfolio.json` file is already included in `.gitignore` to protect your personal data.

## Usage

Once the portfolio is configured, run the script from your terminal:

```bash
python myfinancialticker.py
```

### Sample Output

The output shows daily performance (percentage and absolute variance from the previous close), year-to-date (YTD) performance, trailing 1-year performance, and total performance (percentage and absolute profit/loss), using Yahoo Finance's own labels (`1D`, `YTD`, `1Y`, `T`).

```
1D: ▲ 0.45% (+15.30€) | YTD: ▲ 5.80% (195.50€) | 1Y: ▲ 8.10% (250.00€) | T: ▲ 12.30% (450.00€)
```

## Development

Install the development dependencies (adds `pytest` on top of the runtime requirements) and run the test suite:

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover `load_portfolio` and the pure calculation/formatting logic; they don't hit the network or depend on live market data.