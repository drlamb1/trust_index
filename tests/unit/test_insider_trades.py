"""
Unit tests for ingestion/insider_trades.py

Covers: Form 4 XML parsing, transaction code mapping, cluster buy detection.
No real EDGAR HTTP calls are made.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from core.models import InsiderTrade, InsiderTradeType
from ingestion.insider_trades import (
    TRADE_CODE_MAP,
    detect_cluster_buy,
    parse_form4_xml,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# parse_form4_xml
# ---------------------------------------------------------------------------


class TestParseForm4Xml:
    @pytest.fixture
    def sample_xml(self) -> str:
        return (FIXTURES / "sample_form4.xml").read_text(encoding="utf-8")

    def test_returns_list_of_insider_trades(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        assert isinstance(trades, list)
        assert len(trades) >= 1

    def test_parses_buy_transaction(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        buys = [t for t in trades if t.trade_type == InsiderTradeType.BUY.value]
        assert len(buys) == 1
        buy = buys[0]
        assert buy.shares == pytest.approx(100_000.0)
        assert buy.price_per_share == pytest.approx(495.50)
        assert buy.total_amount == pytest.approx(100_000 * 495.50)

    def test_parses_sell_transaction(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        sells = [t for t in trades if t.trade_type == InsiderTradeType.SELL.value]
        assert len(sells) == 1
        sell = sells[0]
        assert sell.shares == pytest.approx(50_000.0)
        assert sell.price_per_share == pytest.approx(612.75)

    def test_insider_name_extracted(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        assert all(t.insider_name == "HUANG JEN-HSUN" for t in trades)

    def test_insider_title_extracted(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        assert all(t.insider_title == "President and CEO" for t in trades)

    def test_transaction_dates_parsed(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        buys = [t for t in trades if t.trade_type == InsiderTradeType.BUY.value]
        assert buys[0].transaction_date == date(2024, 1, 15)

    def test_shares_after_populated(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        buys = [t for t in trades if t.trade_type == InsiderTradeType.BUY.value]
        assert buys[0].shares_owned_after == pytest.approx(86_920_949.0)

    def test_accession_number_stored(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        assert all(t.accession_number == "0001045810-24-000001" for t in trades)

    def test_ticker_id_stored(self, sample_xml):
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=42)
        assert all(t.ticker_id == 42 for t in trades)

    def test_filed_date_is_none(self, sample_xml):
        """filed_date is populated by caller, not by parse_form4_xml."""
        trades = parse_form4_xml(sample_xml, "0001045810-24-000001", ticker_id=1)
        assert all(t.filed_date is None for t in trades)

    def test_malformed_xml_returns_empty(self):
        trades = parse_form4_xml("<<<not xml>>>", "bad-accession", ticker_id=1)
        assert trades == []

    def test_missing_reporting_owner_returns_empty(self):
        xml = '<?xml version="1.0"?><ownershipDocument></ownershipDocument>'
        trades = parse_form4_xml(xml, "acc-001", ticker_id=1)
        assert trades == []

    def test_skip_code_f_not_included(self):
        """F (tax withholding) transactions should be skipped."""
        xml = """<?xml version="1.0"?>
        <ownershipDocument>
          <reportingOwner>
            <reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId>
            <reportingOwnerRelationship><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
          </reportingOwner>
          <nonDerivativeTable>
            <nonDerivativeTransaction>
              <transactionDate><value>2024-01-15</value></transactionDate>
              <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
              <transactionAmounts>
                <transactionShares><value>500</value></transactionShares>
                <transactionPricePerShare><value>100.0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
              </transactionAmounts>
            </nonDerivativeTransaction>
          </nonDerivativeTable>
        </ownershipDocument>"""
        trades = parse_form4_xml(xml, "acc-skip", ticker_id=1)
        assert trades == []

    def test_acquired_disposed_refines_type(self):
        """P code with D (Disposed) A/D code should become SELL."""
        xml = """<?xml version="1.0"?>
        <ownershipDocument>
          <reportingOwner>
            <reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId>
            <reportingOwnerRelationship><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
          </reportingOwner>
          <nonDerivativeTable>
            <nonDerivativeTransaction>
              <transactionDate><value>2024-03-01</value></transactionDate>
              <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
              <transactionAmounts>
                <transactionShares><value>1000</value></transactionShares>
                <transactionPricePerShare><value>50.0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
              </transactionAmounts>
            </nonDerivativeTransaction>
          </nonDerivativeTable>
        </ownershipDocument>"""
        trades = parse_form4_xml(xml, "acc-ad", ticker_id=1)
        assert len(trades) == 1
        assert trades[0].trade_type == InsiderTradeType.SELL.value


# ---------------------------------------------------------------------------
# detect_cluster_buy
# ---------------------------------------------------------------------------


def _make_buy(name: str, txn_date: date, ticker_id: int = 1) -> InsiderTrade:
    return InsiderTrade(
        ticker_id=ticker_id,
        accession_number=f"acc-{name}-{txn_date}",
        insider_name=name,
        insider_title="Director",
        trade_type=InsiderTradeType.BUY.value,
        shares=1000.0,
        price_per_share=100.0,
        total_amount=100_000.0,
        transaction_date=txn_date,
        filed_date=txn_date,
    )


def _make_sell(name: str, txn_date: date) -> InsiderTrade:
    return InsiderTrade(
        ticker_id=1,
        accession_number=f"acc-sell-{name}-{txn_date}",
        insider_name=name,
        insider_title="Director",
        trade_type=InsiderTradeType.SELL.value,
        shares=1000.0,
        price_per_share=100.0,
        total_amount=100_000.0,
        transaction_date=txn_date,
        filed_date=txn_date,
    )


class TestDetectClusterBuy:
    BASE_DATE = date(2024, 1, 10)

    def test_three_insiders_in_window_is_cluster(self):
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_buy("Bob", self.BASE_DATE + timedelta(days=2)),
            _make_buy("Carol", self.BASE_DATE + timedelta(days=4)),
        ]
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is True

    def test_two_insiders_not_enough(self):
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_buy("Bob", self.BASE_DATE + timedelta(days=2)),
        ]
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is False

    def test_same_insider_not_counted_twice(self):
        """Multiple trades by same insider should only count as one."""
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_buy("Alice", self.BASE_DATE + timedelta(days=1)),
            _make_buy("Alice", self.BASE_DATE + timedelta(days=2)),
        ]
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is False

    def test_buys_outside_window_not_counted(self):
        """Buys more than window_days apart should not form a cluster."""
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_buy("Bob", self.BASE_DATE + timedelta(days=8)),  # Outside 7-day window
            _make_buy("Carol", self.BASE_DATE + timedelta(days=15)),  # Way outside
        ]
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is False

    def test_sells_ignored(self):
        """Sell trades should not contribute to cluster buy detection."""
        trades = [
            _make_sell("Alice", self.BASE_DATE),
            _make_sell("Bob", self.BASE_DATE + timedelta(days=1)),
            _make_sell("Carol", self.BASE_DATE + timedelta(days=2)),
        ]
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is False

    def test_mixed_buys_and_sells(self):
        """Only buys count toward the cluster threshold."""
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_sell("Bob", self.BASE_DATE + timedelta(days=1)),
            _make_buy("Carol", self.BASE_DATE + timedelta(days=2)),
            _make_buy("Dave", self.BASE_DATE + timedelta(days=3)),
        ]
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is True

    def test_empty_trades_returns_false(self):
        assert detect_cluster_buy([], window_days=7, min_insiders=3) is False

    def test_custom_window_and_min_insiders(self):
        """detect_cluster_buy respects custom parameters."""
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_buy("Bob", self.BASE_DATE + timedelta(days=3)),
        ]
        # With min_insiders=2 it should be a cluster
        assert detect_cluster_buy(trades, window_days=7, min_insiders=2) is True
        # With min_insiders=3 it should NOT be a cluster
        assert detect_cluster_buy(trades, window_days=7, min_insiders=3) is False

    def test_no_transaction_date_ignored(self):
        """Trades without a transaction_date should not cause errors."""
        trades = [
            _make_buy("Alice", self.BASE_DATE),
            _make_buy("Bob", self.BASE_DATE + timedelta(days=1)),
            _make_buy("Carol", self.BASE_DATE + timedelta(days=2)),
        ]
        trades[1].transaction_date = None  # Simulate missing date
        # Should still detect cluster from Alice and Carol (with date)
        # But Carol's date is within window of Alice's
        result = detect_cluster_buy(trades, window_days=7, min_insiders=3)
        # Depends on implementation — just ensure no exception
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# TRADE_CODE_MAP constants
# ---------------------------------------------------------------------------


class TestTradeCodeMap:
    def test_p_maps_to_buy(self):
        assert TRADE_CODE_MAP["P"] == InsiderTradeType.BUY

    def test_s_maps_to_sell(self):
        assert TRADE_CODE_MAP["S"] == InsiderTradeType.SELL

    def test_a_maps_to_grant(self):
        assert TRADE_CODE_MAP["A"] == InsiderTradeType.GRANT

    def test_m_maps_to_exercise(self):
        assert TRADE_CODE_MAP["M"] == InsiderTradeType.EXERCISE
