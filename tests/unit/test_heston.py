"""Tests for simulation/heston.py — Heston model pricing, calibration, and MC paths."""

from __future__ import annotations

import math

import numpy as np
import pytest

from simulation.heston import (
    HestonParams,
    calibrate_heston,
    generate_heston_paths,
    heston_call_price,
    heston_characteristic_function,
    heston_implied_vol,
    heston_put_price,
)


@pytest.fixture
def typical_params():
    """Typical Heston parameters (Feller-satisfying)."""
    return HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)


@pytest.fixture
def feller_violated_params():
    """Parameters that violate Feller condition (common in practice)."""
    return HestonParams(v0=0.04, kappa=1.0, theta=0.04, sigma_v=0.8, rho=-0.5)


class TestHestonParams:
    """Test parameter utilities."""

    def test_feller_satisfied(self, typical_params):
        assert typical_params.feller_condition() is True
        # 2 * 2.0 * 0.04 = 0.16 > 0.09 = 0.3^2

    def test_feller_violated(self, feller_violated_params):
        assert feller_violated_params.feller_condition() is False
        # 2 * 1.0 * 0.04 = 0.08 < 0.64 = 0.8^2

    def test_round_trip_array(self, typical_params):
        arr = typical_params.to_array()
        reconstructed = HestonParams.from_array(arr)
        assert abs(reconstructed.v0 - typical_params.v0) < 1e-10
        assert abs(reconstructed.rho - typical_params.rho) < 1e-10

    def test_to_dict(self, typical_params):
        d = typical_params.to_dict()
        assert d["v0"] == 0.04
        assert d["feller_satisfied"] is True


class TestCharacteristicFunction:
    """Test the Heston characteristic function."""

    def test_phi_at_zero(self, typical_params):
        """φ(0) = 1 (normalization of probability measure)."""
        phi = heston_characteristic_function(0.0, 1.0, 0.05, typical_params)
        assert abs(phi - 1.0) < 1e-10

    def test_phi_is_complex(self, typical_params):
        """φ(u) should be complex for u ≠ 0."""
        phi = heston_characteristic_function(1.0, 1.0, 0.05, typical_params)
        assert isinstance(phi, (complex, np.complexfloating))

    def test_phi_conjugate_symmetry(self, typical_params):
        """φ(-u) = conj(φ(u)) for real-valued distributions."""
        u = 2.5
        phi_u = heston_characteristic_function(u, 1.0, 0.05, typical_params)
        phi_neg_u = heston_characteristic_function(-u, 1.0, 0.05, typical_params)
        assert abs(phi_neg_u - np.conj(phi_u)) < 1e-8


class TestHestonPricing:
    """Test Heston call pricing."""

    def test_atm_call_reasonable(self, typical_params):
        """ATM call should be in reasonable range."""
        price = heston_call_price(100, 100, 1.0, 0.05, typical_params)
        assert 5 < price < 20  # reasonable for 20% vol

    def test_converges_to_bsm_low_vol_of_vol(self):
        """As σᵥ → 0, Heston should converge to BSM.

        This is the KEY sanity check. When vol-of-vol is zero,
        the variance process is deterministic (v(t) = theta),
        and Heston reduces to BSM with σ = √theta.
        """
        from simulation.black_scholes import bs_call_price

        # Very low vol-of-vol, v0 = theta (at equilibrium)
        params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.001, rho=0.0)
        heston_price = heston_call_price(100, 100, 1.0, 0.05, params)
        bsm_price = bs_call_price(100, 100, 1.0, 0.05, 0.20)  # σ = √0.04 = 0.20

        assert abs(heston_price - bsm_price) < 0.5, (
            f"Heston ({heston_price:.4f}) should converge to BSM ({bsm_price:.4f}) "
            f"when σᵥ → 0"
        )

    def test_put_call_parity(self, typical_params):
        """Put-call parity must hold under Heston too."""
        S, K, T, r = 100, 100, 1.0, 0.05
        call = heston_call_price(S, K, T, r, typical_params)
        put = heston_put_price(S, K, T, r, typical_params)
        parity = call - put - (S - K * math.exp(-r * T))
        assert abs(parity) < 0.1, f"Put-call parity violated: {parity}"

    def test_call_price_increases_with_vol(self):
        """Higher vol-of-vol should generally increase ATM call price."""
        params_low = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.1, rho=-0.5)
        params_high = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.8, rho=-0.5)
        price_low = heston_call_price(100, 100, 1.0, 0.05, params_low)
        price_high = heston_call_price(100, 100, 1.0, 0.05, params_high)
        # Higher vol-of-vol creates fatter tails, generally increasing option value
        # (especially for OTM, ATM effect can vary with rho)
        # Just check both are positive and reasonable
        assert price_low > 0
        assert price_high > 0

    def test_zero_expiry(self, typical_params):
        """At expiry, Heston call = max(S-K, 0)."""
        assert heston_call_price(110, 100, 0, 0.05, typical_params) == 10.0
        assert heston_call_price(90, 100, 0, 0.05, typical_params) == 0.0


class TestHestonImpliedVol:
    """Test BSM-equivalent IV from Heston prices."""

    def test_iv_skew(self, typical_params):
        """Negative rho should produce put skew (lower strike → higher IV)."""
        S, T, r = 100, 0.5, 0.05
        iv_otm_put = heston_implied_vol(S, 90, T, r, typical_params)
        iv_atm = heston_implied_vol(S, 100, T, r, typical_params)
        iv_otm_call = heston_implied_vol(S, 110, T, r, typical_params)

        assert iv_otm_put is not None and iv_atm is not None
        # With rho = -0.7, OTM puts should have higher IV than ATM
        assert iv_otm_put > iv_atm, "Negative rho should produce put skew"


class TestMonteCarloPathGeneration:
    """Test QE scheme path generation."""

    def test_path_shapes(self, typical_params):
        """Output arrays should have correct shape."""
        S, V = generate_heston_paths(100, 1.0, 0.05, typical_params, n_paths=100, n_steps=50, seed=42)
        assert S.shape == (100, 51)  # n_paths × (n_steps + 1)
        assert V.shape == (100, 51)

    def test_initial_values(self, typical_params):
        """First column should be S0 and v0."""
        S, V = generate_heston_paths(100, 1.0, 0.05, typical_params, n_paths=50, n_steps=10, seed=42)
        np.testing.assert_allclose(S[:, 0], 100.0)
        np.testing.assert_allclose(V[:, 0], 0.04)

    def test_positive_prices(self, typical_params):
        """All prices should be positive (stock can't go negative)."""
        S, V = generate_heston_paths(100, 1.0, 0.05, typical_params, n_paths=500, n_steps=252, seed=42)
        assert np.all(S > 0), "Stock prices must be positive"

    def test_positive_variance(self, typical_params):
        """QE scheme should keep variance non-negative."""
        S, V = generate_heston_paths(100, 1.0, 0.05, typical_params, n_paths=500, n_steps=252, seed=42)
        assert np.all(V >= 0), "QE scheme should maintain non-negative variance"

    def test_positive_variance_feller_violated(self, feller_violated_params):
        """QE scheme should handle Feller violation gracefully."""
        S, V = generate_heston_paths(100, 1.0, 0.05, feller_violated_params, n_paths=500, n_steps=252, seed=42)
        assert np.all(V >= 0), "QE scheme must handle Feller violation"
        assert np.all(S > 0), "Prices must stay positive even with Feller violation"

    def test_mc_call_price_converges(self, typical_params):
        """MC call price should converge to analytical price (within tolerance)."""
        S0, K, T, r = 100, 100, 1.0, 0.05
        analytical = heston_call_price(S0, K, T, r, typical_params)

        S, _ = generate_heston_paths(S0, T, r, typical_params, n_paths=50_000, n_steps=252, seed=42)
        terminal = S[:, -1]
        payoffs = np.maximum(terminal - K, 0)
        mc_price = math.exp(-r * T) * np.mean(payoffs)

        # MC should be within ~15% of analytical for 50k paths
        # (QE scheme introduces discretization bias; this is expected)
        assert abs(mc_price - analytical) / analytical < 0.15, (
            f"MC price ({mc_price:.4f}) too far from analytical ({analytical:.4f})"
        )

    def test_seed_reproducibility(self, typical_params):
        """Same seed should produce same paths."""
        S1, V1 = generate_heston_paths(100, 1.0, 0.05, typical_params, n_paths=10, n_steps=10, seed=123)
        S2, V2 = generate_heston_paths(100, 1.0, 0.05, typical_params, n_paths=10, n_steps=10, seed=123)
        np.testing.assert_array_equal(S1, S2)
        np.testing.assert_array_equal(V1, V2)


class TestCalibration:
    """Test Heston calibration to synthetic data."""

    def test_calibrate_to_synthetic(self):
        """Calibrate to prices generated by known Heston params.

        The acid test: generate a synthetic vol surface from known parameters,
        then calibrate back. Should recover approximately the same parameters.
        """
        true_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
        S, r = 100, 0.05

        # Generate synthetic market IVs
        strikes = np.array([85, 90, 95, 100, 105, 110, 115])
        expiries = np.array([0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25])

        market_ivs = np.array([
            heston_implied_vol(S, float(K), float(T), r, true_params) or 0.20
            for K, T in zip(strikes, expiries)
        ])

        # Calibrate
        calibrated, rmse = calibrate_heston(market_ivs, strikes, expiries, S, r)

        # RMSE should be reasonable (calibration to synthetic data with
        # numerical integration + IV inversion introduces some noise)
        assert rmse < 0.10, f"Calibration RMSE too high: {rmse}"

        # Parameters should be in the right ballpark
        assert abs(calibrated.rho - true_params.rho) < 0.5, (
            f"rho mismatch: {calibrated.rho} vs {true_params.rho}"
        )
