import json
from datetime import date

import pandas as pd
import pytest

import myfinancialticker as mft


def test_load_portfolio_valid(tmp_path):
    portfolio_file = tmp_path / "portfolio.json"
    portfolio_file.write_text(json.dumps({"AAPL": [2, 150.0]}))

    result = mft.load_portfolio(str(portfolio_file))

    assert result == {"AAPL": [2, 150.0]}


def test_load_portfolio_missing_file(tmp_path):
    missing_file = tmp_path / "does_not_exist.json"

    with pytest.raises(SystemExit):
        mft.load_portfolio(str(missing_file))


def test_load_portfolio_invalid_json(tmp_path):
    bad_file = tmp_path / "portfolio.json"
    bad_file.write_text("{not valid json")

    with pytest.raises(SystemExit):
        mft.load_portfolio(str(bad_file))


def test_format_performance_positive_change():
    result = mft.format_performance(
        total_cost=1000,
        current_total_value=1200,
        yesterday_total_value=1190,
        ytd_start_total_value=1100,
        year_start_total_value=1050,
    )

    assert result.startswith("1D: ▲")
    assert "YTD: ▲" in result
    assert "1Y: ▲" in result
    assert "T: ▲" in result


def test_format_performance_negative_change():
    result = mft.format_performance(
        total_cost=1000,
        current_total_value=800,
        yesterday_total_value=820,
        ytd_start_total_value=900,
        year_start_total_value=950,
    )

    assert result.startswith("1D: ▼")
    assert "YTD: ▼" in result
    assert "1Y: ▼" in result
    assert "T: ▼" in result


def test_format_performance_zero_total_cost_is_error_sentinel():
    result = mft.format_performance(
        total_cost=0,
        current_total_value=0,
        yesterday_total_value=0,
        ytd_start_total_value=0,
        year_start_total_value=0,
    )

    assert result == "ETF: Error"


def test_format_performance_zero_start_values_do_not_raise():
    result = mft.format_performance(
        total_cost=1000,
        current_total_value=1200,
        yesterday_total_value=0,
        ytd_start_total_value=0,
        year_start_total_value=0,
    )

    assert "1D: ▲ 0.00%" in result
    assert "YTD: ▲ 0.00%" in result
    assert "1Y: ▲ 0.00%" in result


def test_closing_price_on_or_before_finds_prior_close():
    hist = pd.DataFrame(
        {"Close": [10.0, 11.0, 12.0]},
        index=pd.to_datetime(["2025-12-29", "2025-12-30", "2025-12-31"]),
    )

    price = mft._closing_price_on_or_before(hist, date(2025, 12, 31), fallback=999.0)

    assert price == 12.0


def test_closing_price_on_or_before_uses_fallback_when_no_prior_row():
    hist = pd.DataFrame(
        {"Close": [10.0]},
        index=pd.to_datetime(["2026-01-05"]),
    )

    price = mft._closing_price_on_or_before(hist, date(2025, 12, 31), fallback=999.0)

    assert price == 999.0


def test_closing_price_on_or_before_uses_fallback_when_history_empty():
    hist = pd.DataFrame({"Close": []})

    price = mft._closing_price_on_or_before(hist, date(2025, 12, 31), fallback=999.0)

    assert price == 999.0
