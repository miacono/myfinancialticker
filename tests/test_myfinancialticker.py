import json
from datetime import date, timedelta

import pandas as pd
import pytest

import myfinancialticker as mft


class _FakeTicker:
    """Stand-in for yf.Ticker: reads canned responses instead of hitting Yahoo Finance."""

    def __init__(self, symbol, config):
        self._symbol = symbol
        self._config = config[symbol]
        if self._config.get("raise_on_init"):
            raise RuntimeError(f"forced failure creating ticker for {symbol}")

    @property
    def fast_info(self):
        if self._config.get("raise_on_fast_info"):
            raise RuntimeError(f"forced fast_info failure for {self._symbol}")
        return self._config["fast_info"]

    def history(self, start=None, end=None):
        if self._config.get("raise_on_history"):
            raise RuntimeError(f"forced history failure for {self._symbol}")
        return self._config["history"]


def _hist_df(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.to_datetime(dates))


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


def test_get_performance_happy_path_mixed_currencies(monkeypatch):
    today = date.today()
    yesterday = today - timedelta(days=1)

    # No row goes further back than "yesterday", so YTD/1Y both fall back
    # to prev_close, same as the daily figures. This keeps the expected
    # values deterministic regardless of which day the suite runs on.
    eur_hist = _hist_df([yesterday, today], [100.0, 120.0])
    usd_hist = _hist_df([yesterday, today], [50.0, 60.0])

    config = {
        "EURUSD=X": {"fast_info": {"last_price": 1.10}},
        "EUR_TICKER": {"fast_info": {"currency": "EUR"}, "history": eur_hist},
        "USD_TICKER": {"fast_info": {"currency": "USD"}, "history": usd_hist},
    }
    monkeypatch.setattr(
        mft, "load_portfolio", lambda: {"EUR_TICKER": [2, 90.0], "USD_TICKER": [3, 40.0]}
    )
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    usd_eur_rate = 1 / 1.10
    total_cost = 2 * 90.0 + 3 * 40.0
    current_total_value = 2 * 120.0 + 3 * (60.0 * usd_eur_rate)
    yesterday_total_value = 2 * 100.0 + 3 * (50.0 * usd_eur_rate)
    expected = mft.format_performance(
        total_cost,
        current_total_value,
        yesterday_total_value,
        yesterday_total_value,
        yesterday_total_value,
    )

    assert result == expected


def test_get_performance_eurusd_fetch_failure_uses_fallback_rate(monkeypatch):
    today = date.today()
    yesterday = today - timedelta(days=1)
    usd_hist = _hist_df([yesterday, today], [50.0, 60.0])

    config = {
        "EURUSD=X": {"raise_on_init": True},
        "USD_TICKER": {"fast_info": {"currency": "USD"}, "history": usd_hist},
    }
    monkeypatch.setattr(mft, "load_portfolio", lambda: {"USD_TICKER": [1, 40.0]})
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    fallback_rate = 0.92
    total_cost = 40.0
    current_total_value = 60.0 * fallback_rate
    yesterday_total_value = 50.0 * fallback_rate
    expected = mft.format_performance(
        total_cost,
        current_total_value,
        yesterday_total_value,
        yesterday_total_value,
        yesterday_total_value,
    )

    assert result == expected


def test_get_performance_skips_ticker_that_raises(monkeypatch):
    today = date.today()
    yesterday = today - timedelta(days=1)
    good_hist = _hist_df([yesterday, today], [10.0, 12.0])

    config = {
        "EURUSD=X": {"fast_info": {"last_price": 1.0}},
        "GOOD": {"fast_info": {"currency": "EUR"}, "history": good_hist},
        "BAD": {"fast_info": {"currency": "EUR"}, "raise_on_history": True},
    }
    monkeypatch.setattr(
        mft, "load_portfolio", lambda: {"GOOD": [1, 9.0], "BAD": [1, 9.0]}
    )
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    # BAD is skipped entirely: only GOOD contributes to the totals.
    expected = mft.format_performance(9.0, 12.0, 10.0, 10.0, 10.0)

    assert result == expected


def test_get_performance_single_row_history_uses_current_price_as_prev_close(monkeypatch):
    today = date.today()
    hist = _hist_df([today], [42.0])

    config = {
        "EURUSD=X": {"fast_info": {"last_price": 1.0}},
        "ONLY": {"fast_info": {"currency": "EUR"}, "history": hist},
    }
    monkeypatch.setattr(mft, "load_portfolio", lambda: {"ONLY": [1, 40.0]})
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    expected = mft.format_performance(40.0, 42.0, 42.0, 42.0, 42.0)

    assert result == expected
    assert "1D: ▲ 0.00%" in result


def test_get_performance_empty_portfolio_returns_error_sentinel(monkeypatch):
    config = {"EURUSD=X": {"fast_info": {"last_price": 1.0}}}
    monkeypatch.setattr(mft, "load_portfolio", lambda: {})
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    assert result == "ETF: Error"


def test_main_prints_get_performance_result(monkeypatch, capsys):
    monkeypatch.setattr(mft, "get_performance", lambda: "1D: ▲ 1.00% (+1.00€)")

    mft.main()

    captured = capsys.readouterr()
    assert captured.out == "1D: ▲ 1.00% (+1.00€)\n"


def test_main_prints_error_message_on_exception(monkeypatch, capsys):
    def _raise():
        raise RuntimeError("network down")

    monkeypatch.setattr(mft, "get_performance", _raise)

    mft.main()

    captured = capsys.readouterr()
    assert captured.out == "Error: network down\n"
