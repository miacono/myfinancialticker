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


# A purchase date old enough to always be "held" as of any reference window
# used in these tests, keeping _value_as_of's market-price branch selected.
_LONG_AGO = "2000-01-01"


def test_load_portfolio_valid(tmp_path):
    portfolio_file = tmp_path / "portfolio.json"
    portfolio_file.write_text(json.dumps({"AAPL": [[2, 150.0, "2025-01-01"]]}))

    result = mft.load_portfolio(str(portfolio_file))

    assert result == {"AAPL": [[2, 150.0, "2025-01-01"]]}


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
        five_days_start_total_value=1150,
        one_month_start_total_value=1120,
        ytd_start_total_value=1100,
        year_start_total_value=1050,
    )

    assert result.startswith("1D: ▲")
    assert "5D: ▲" in result
    assert "1M: ▲" in result
    assert "YTD: ▲" in result
    assert "1Y: ▲" in result
    assert "T: ▲" in result


def test_format_performance_negative_change():
    result = mft.format_performance(
        total_cost=1000,
        current_total_value=800,
        yesterday_total_value=820,
        five_days_start_total_value=850,
        one_month_start_total_value=880,
        ytd_start_total_value=900,
        year_start_total_value=950,
    )

    assert result.startswith("1D: ▼")
    assert "5D: ▼" in result
    assert "1M: ▼" in result
    assert "YTD: ▼" in result
    assert "1Y: ▼" in result
    assert "T: ▼" in result


def test_format_performance_zero_total_cost_is_error_sentinel():
    result = mft.format_performance(
        total_cost=0,
        current_total_value=0,
        yesterday_total_value=0,
        five_days_start_total_value=0,
        one_month_start_total_value=0,
        ytd_start_total_value=0,
        year_start_total_value=0,
    )

    assert result == "ETF: Error"


def test_format_performance_zero_start_values_do_not_raise():
    result = mft.format_performance(
        total_cost=1000,
        current_total_value=1200,
        yesterday_total_value=0,
        five_days_start_total_value=0,
        one_month_start_total_value=0,
        ytd_start_total_value=0,
        year_start_total_value=0,
    )

    assert "1D: ▲ 0.00%" in result
    assert "5D: ▲ 0.00%" in result
    assert "1M: ▲ 0.00%" in result
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


def test_n_trading_sessions_ago_skips_weekends():
    # 8 consecutive trading sessions (Mon-Thu, Mon-Thu), no weekend rows --
    # mirrors what yfinance actually returns, unlike a gapless calendar range.
    dates = [
        "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30",  # Mon-Thu
        "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06",  # Mon-Thu
    ]
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]
    hist = _hist_df(dates, closes)

    result_date, result_price = mft._n_trading_sessions_ago(
        hist, 5, fallback_date=date(2000, 1, 1), fallback_price=-1.0
    )

    # 5 sessions back from 2026-08-06 (the last row) is 2026-07-29, not the
    # calendar date 5 days earlier (2026-08-01, a Saturday with no session).
    assert result_date == date(2026, 7, 29)
    assert result_price == 102.0


def test_n_trading_sessions_ago_uses_fallback_when_not_enough_rows():
    hist = _hist_df(["2026-08-05", "2026-08-06"], [10.0, 11.0])

    result_date, result_price = mft._n_trading_sessions_ago(
        hist, 5, fallback_date=date(2000, 1, 1), fallback_price=-1.0
    )

    assert result_date == date(2000, 1, 1)
    assert result_price == -1.0


def test_value_as_of_all_lots_held_uses_market_price():
    lots = [[10, 5.0, "2024-01-01"], [4, 8.0, "2024-02-01"]]

    value = mft._value_as_of(lots, date(2024, 3, 1), market_price=6.0)

    assert value == 14 * 6.0


def test_value_as_of_no_lots_held_yet_uses_cost():
    lots = [[10, 5.0, "2024-06-01"]]

    value = mft._value_as_of(lots, date(2024, 3, 1), market_price=6.0)

    assert value == 10 * 5.0


def test_value_as_of_mixes_market_and_cost_priced_lots():
    lots = [
        [10, 5.0, "2024-01-01"],  # already held on target_date: priced at market
        [4, 8.0, "2024-06-01"],  # bought after target_date: priced at its own cost
    ]

    value = mft._value_as_of(lots, date(2024, 3, 1), market_price=6.0)

    assert value == 10 * 6.0 + 4 * 8.0


def test_value_as_of_boundary_purchase_date_counts_as_held():
    lots = [[10, 5.0, "2024-03-01"]]

    value = mft._value_as_of(lots, date(2024, 3, 1), market_price=6.0)

    assert value == 10 * 6.0


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
        mft,
        "load_portfolio",
        lambda: {
            "EUR_TICKER": [[2, 90.0, _LONG_AGO]],
            "USD_TICKER": [[3, 40.0, _LONG_AGO]],
        },
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
    monkeypatch.setattr(
        mft, "load_portfolio", lambda: {"USD_TICKER": [[1, 40.0, _LONG_AGO]]}
    )
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
        mft,
        "load_portfolio",
        lambda: {
            "GOOD": [[1, 9.0, _LONG_AGO]],
            "BAD": [[1, 9.0, _LONG_AGO]],
        },
    )
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    # BAD is skipped entirely: only GOOD contributes to the totals.
    expected = mft.format_performance(9.0, 12.0, 10.0, 10.0, 10.0, 10.0, 10.0)

    assert result == expected


def test_get_performance_single_row_history_uses_current_price_as_prev_close(monkeypatch):
    today = date.today()
    hist = _hist_df([today], [42.0])

    config = {
        "EURUSD=X": {"fast_info": {"last_price": 1.0}},
        "ONLY": {"fast_info": {"currency": "EUR"}, "history": hist},
    }
    monkeypatch.setattr(
        mft, "load_portfolio", lambda: {"ONLY": [[1, 40.0, _LONG_AGO]]}
    )
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    expected = mft.format_performance(40.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0)

    assert result == expected
    assert "1D: ▲ 0.00%" in result


def test_get_performance_multiple_lots_value_correctly_by_purchase_date(monkeypatch):
    today = date.today()
    first_purchase_date = today - timedelta(days=200)
    second_purchase_date = today - timedelta(days=3)  # after five_days_ago

    # 40 days of real, distinct closes so 5D/1M resolve from history.
    dates = [today - timedelta(days=offset) for offset in range(39, -1, -1)]
    closes = [100.0 + i for i in range(len(dates))]
    hist = _hist_df(dates, closes)

    lots = [
        [1, 50.0, first_purchase_date.isoformat()],
        [1, 90.0, second_purchase_date.isoformat()],
    ]

    config = {
        "EURUSD=X": {"fast_info": {"last_price": 1.0}},
        "NEW": {"fast_info": {"currency": "EUR"}, "history": hist},
    }
    monkeypatch.setattr(mft, "load_portfolio", lambda: {"NEW": lots})
    monkeypatch.setattr(mft.yf, "Ticker", lambda symbol: _FakeTicker(symbol, config))

    result = mft.get_performance()

    current_price = hist["Close"].iloc[-1]
    prev_close = hist["Close"].iloc[-2]
    five_days_start_date, five_days_start_price = mft._n_trading_sessions_ago(
        hist, 5, today - timedelta(days=5), prev_close
    )

    expected = mft.format_performance(
        total_cost=50.0 + 90.0,
        current_total_value=2 * current_price,
        yesterday_total_value=mft._value_as_of(lots, today - timedelta(days=1), prev_close),
        five_days_start_total_value=mft._value_as_of(lots, five_days_start_date, five_days_start_price),
        one_month_start_total_value=mft._value_as_of(
            lots, today - timedelta(days=30), mft._closing_price_on_or_before(hist, today - timedelta(days=30), prev_close)
        ),
        ytd_start_total_value=mft._value_as_of(
            lots, date(today.year - 1, 12, 31), mft._closing_price_on_or_before(hist, date(today.year - 1, 12, 31), prev_close)
        ),
        year_start_total_value=mft._value_as_of(
            lots, today - timedelta(days=365), mft._closing_price_on_or_before(hist, today - timedelta(days=365), prev_close)
        ),
    )

    assert result == expected
    # 1Y always predates both purchases (200/3 days ago), so it's cost-only.
    assert mft._value_as_of(lots, today - timedelta(days=365), 999.0) == 50.0 + 90.0
    # 5D is after the first purchase but before the second: mixed pricing.
    five_days_ago = today - timedelta(days=5)
    assert mft._value_as_of(lots, five_days_ago, 77.0) == 77.0 + 90.0


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
