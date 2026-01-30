import yfinance as yf
import pandas as pd
import warnings
import json
import sys
import os

warnings.filterwarnings("ignore")


def load_portfolio(filename="portfolio.json"):
    """Loads the portfolio from a JSON file, searching for it in the same directory as the script."""
    # Calculate the absolute path for the configuration file
    # based on the script's location.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, filename)
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"Error: Configuration file '{config_path}' not found.")
    except json.JSONDecodeError:
        sys.exit(f"Error: The file '{config_path}' is not a valid JSON.")

def get_performance():
    MY_PORTFOLIO = load_portfolio()
    total_cost = 0
    current_total_value = 0
    yesterday_total_value = 0

    # 1. Get the current EUR/USD exchange rate (e.g., 1.08)
    # We use the special ticker 'EURUSD=X'
    try:
        usd_eur_rate = 1 / yf.Ticker("EURUSD=X").fast_info['last_price']
    except:
        usd_eur_rate = 0.92  # Manual fallback if the exchange rate fetch fails

    for symbol, data in MY_PORTFOLIO.items():
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            
            # Ticker's currency (e.g., 'EUR' or 'USD')
            currency = info.get('currency', 'EUR')
            
            qty, cost = data # Unpack quantity and cost from the list

            current_price = info['last_price']
            prev_close = info['regular_market_previous_close']
            
            # 2. If the data is in USD, convert it to EUR
            if currency == 'USD':
                current_price *= usd_eur_rate
                prev_close *= usd_eur_rate
            
            total_cost += qty * cost
            current_total_value += qty * current_price
            yesterday_total_value += qty * prev_close
        except Exception:
            continue

    if total_cost == 0: return "ETF: Error"

    # Final calculations
    total_net = current_total_value - total_cost
    total_perc = (total_net / total_cost) * 100
    daily_net = current_total_value - yesterday_total_value
    daily_perc = (daily_net / yesterday_total_value) * 100

    t_icon = "▲" if total_net >= 0 else "▼"
    d_icon = "▲" if daily_net >= 0 else "▼"
    
    return f"{d_icon}{daily_perc:.2f}% ({daily_net:+.2f}€) | {t_icon}{total_perc:.2f}% ({total_net:.2f}€)"

if __name__ == "__main__":
    try:
        print(get_performance())
    except Exception as e:
        print(f"Error: {e}")