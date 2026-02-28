"""Tests for the deep hedging step() delta_change bug fix.

Original bug: delta_change = abs(action_delta - action_delta) → always 0
Fixed:        delta_change = abs(action_delta - prev_delta)

This test verifies that the DeepHedgingEnv correctly computes transaction
costs when the hedge ratio changes between steps.
"""

from __future__ import annotations

import numpy as np
import pytest

from simulation.deep_hedging import DeepHedgingEnv, HedgingState


@pytest.fixture
def simple_env() -> DeepHedgingEnv:
    """Create a simple environment with known paths for testing."""
    # 3 paths, 5 steps each → shape (3, 6) including initial
    price_paths = np.array([
        [100, 101, 102, 103, 104, 105],
        [100, 99, 98, 97, 96, 95],
        [100, 100, 100, 100, 100, 100],  # flat path
    ], dtype=np.float64)

    variance_paths = np.full_like(price_paths, 0.04)

    return DeepHedgingEnv(
        price_paths=price_paths,
        variance_paths=variance_paths,
        strike=100.0,
        risk_free_rate=0.05,
        transaction_cost=0.01,  # 100 bps for easy calculation
    )


class TestDeltaChangeBugFix:
    """Verify that delta_change is computed correctly in step()."""

    def test_first_step_from_zero(self, simple_env):
        """First step: delta changes from 0 to action_delta."""
        simple_env.reset(path_idx=0)
        state, cost, done = simple_env.step(0.5)

        # Transaction cost = 0.01 * |0.5 - 0.0| * 100 = 0.50
        expected_cost = 0.01 * 0.5 * 100
        assert cost == pytest.approx(expected_cost, abs=1e-10)

    def test_nonzero_cost_on_rebalance(self, simple_env):
        """Subsequent steps should have nonzero cost when delta changes."""
        simple_env.reset(path_idx=0)

        # Step 1: delta goes from 0 to 0.6
        _, cost1, _ = simple_env.step(0.6)
        assert cost1 > 0, "First step should have nonzero cost"

        # Step 2: delta goes from 0.6 to 0.8
        _, cost2, _ = simple_env.step(0.8)
        # Cost = 0.01 * |0.8 - 0.6| * S_t
        expected_cost2 = 0.01 * 0.2 * 101  # price at t=1 is 101
        assert cost2 == pytest.approx(expected_cost2, abs=1e-10)
        assert cost2 > 0, "BUG: delta change was always 0 before fix"

    def test_zero_cost_when_delta_unchanged(self, simple_env):
        """No cost when maintaining the same delta."""
        simple_env.reset(path_idx=0)

        # Step 1: delta to 0.5
        simple_env.step(0.5)

        # Step 2: same delta (no change)
        _, cost2, _ = simple_env.step(0.5)
        assert cost2 == pytest.approx(0.0, abs=1e-10)

    def test_accumulated_costs_over_path(self, simple_env):
        """Total costs should accumulate across the full path."""
        simple_env.reset(path_idx=2)  # flat path: all prices = 100

        total_cost = 0.0

        # Step through with increasing deltas
        deltas = [0.2, 0.5, 0.8, 0.3, 0.3]
        prev_delta = 0.0

        for delta in deltas:
            _, cost, done = simple_env.step(delta)
            expected = 0.01 * abs(delta - prev_delta) * 100
            assert cost == pytest.approx(expected, abs=1e-10), (
                f"Cost mismatch at delta={delta}, prev={prev_delta}"
            )
            total_cost += cost
            prev_delta = delta

        # Total expected: sum of |delta_changes| * 0.01 * 100
        # |0.2-0| + |0.5-0.2| + |0.8-0.5| + |0.3-0.8| + |0.3-0.3|
        # = 0.2 + 0.3 + 0.3 + 0.5 + 0.0 = 1.3
        expected_total = 0.01 * 1.3 * 100
        assert total_cost == pytest.approx(expected_total, abs=1e-10)

    def test_delta_change_with_sign_reversal(self, simple_env):
        """Cost should be correct even when delta goes from positive to negative."""
        simple_env.reset(path_idx=0)

        # Delta from 0 to +0.8
        simple_env.step(0.8)

        # Delta from +0.8 to -0.5 (large change)
        _, cost, _ = simple_env.step(-0.5)
        # |(-0.5) - 0.8| = 1.3
        expected = 0.01 * 1.3 * 101  # price at t=1
        assert cost == pytest.approx(expected, abs=1e-10)


class TestHedgingStateTracking:
    """Verify that the state correctly tracks current_delta."""

    def test_state_reflects_action_delta(self, simple_env):
        """The returned state's current_delta should match the action."""
        simple_env.reset(path_idx=0)

        state, _, _ = simple_env.step(0.7)
        assert state.current_delta == 0.7

    def test_reset_clears_delta(self, simple_env):
        """After reset, previous delta should be 0."""
        simple_env.reset(path_idx=0)
        simple_env.step(0.9)

        # Reset and step again
        simple_env.reset(path_idx=0)
        _, cost, _ = simple_env.step(0.3)

        # Should compute change from 0.0 (reset), not 0.9
        expected = 0.01 * 0.3 * 100
        assert cost == pytest.approx(expected, abs=1e-10)


class TestComputeTerminalPnl:
    """Tests for compute_terminal_pnl (uses the same delta tracking)."""

    def test_constant_delta_has_correct_costs(self, simple_env):
        """A constant hedge ratio should only incur cost at the first step."""
        # Delta = [0.5, 0.5, 0.5, 0.5, 0.5]
        deltas = np.array([0.5, 0.5, 0.5, 0.5, 0.5])
        pnl = simple_env.compute_terminal_pnl(deltas, path_idx=2)  # flat path

        # Only the first step has a delta change (0 → 0.5)
        # Total cost = 0.01 * 0.5 * 100 = 0.5
        # Option payoff at S_T=100, K=100: max(0, 0) = 0
        # Hedge P&L on flat path: all price changes = 0
        # Net PnL = 0 - 0 - 0.5 = -0.5
        assert pnl == pytest.approx(-0.5, abs=1e-10)

    def test_itm_option_payoff(self, simple_env):
        """In-the-money option payoff is correctly accounted for."""
        # Path 0: S_T = 105, K = 100 → payoff = 5
        deltas = np.zeros(5)  # no hedging
        pnl = simple_env.compute_terminal_pnl(deltas, path_idx=0)

        # compute_terminal_pnl = option_payoff - hedge_pnl - total_costs
        # = 5 - 0 - 0 = 5
        assert pnl == pytest.approx(5.0, abs=1e-10)
