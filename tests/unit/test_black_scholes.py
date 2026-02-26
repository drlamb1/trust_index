"""Tests for simulation/black_scholes.py — BSM pricing, Greeks, and IV solver."""

from __future__ import annotations

import math

import numpy as np
import pytest

from simulation.black_scholes import (
    bs_call_price,
    bs_call_price_vec,
    bs_greeks,
    bs_implied_vol,
    bs_implied_vol_vec,
    bs_put_price,
)


class TestBSCallPrice:
    """Black-Scholes call pricing tests against known values."""

    def test_atm_call(self):
        """ATM call with known parameters."""
        # S=100, K=100, T=1, r=5%, sigma=20%
        price = bs_call_price(100, 100, 1.0, 0.05, 0.20)
        # Known value: ~10.45
        assert 10.0 < price < 11.0

    def test_deep_itm_call(self):
        """Deep ITM call ≈ S - K·e^(-rT)."""
        price = bs_call_price(150, 100, 1.0, 0.05, 0.20)
        intrinsic = 150 - 100 * math.exp(-0.05)
        assert price > intrinsic
        assert price < 150  # can't exceed spot

    def test_deep_otm_call(self):
        """Deep OTM call → near zero."""
        price = bs_call_price(50, 100, 0.1, 0.05, 0.20)
        assert price < 0.01

    def test_zero_expiry(self):
        """At expiry, call = max(S-K, 0)."""
        assert bs_call_price(110, 100, 0, 0.05, 0.20) == 10.0
        assert bs_call_price(90, 100, 0, 0.05, 0.20) == 0.0

    def test_zero_vol(self):
        """Zero vol: call = max(S - K·e^(-rT), 0)."""
        price = bs_call_price(100, 95, 1.0, 0.05, 0.0)
        expected = 100 - 95 * math.exp(-0.05)
        assert abs(price - expected) < 0.01


class TestBSPutPrice:
    """Put pricing and put-call parity tests."""

    def test_put_call_parity(self):
        """C - P = S - K·e^(-rT) must hold for any parameters."""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.30
        call = bs_call_price(S, K, T, r, sigma)
        put = bs_put_price(S, K, T, r, sigma)
        parity = call - put - (S - K * math.exp(-r * T))
        assert abs(parity) < 1e-10, f"Put-call parity violated: {parity}"

    def test_put_call_parity_itm(self):
        """Parity for ITM options."""
        S, K, T, r, sigma = 120, 100, 0.5, 0.03, 0.25
        call = bs_call_price(S, K, T, r, sigma)
        put = bs_put_price(S, K, T, r, sigma)
        parity = call - put - (S - K * math.exp(-r * T))
        assert abs(parity) < 1e-10

    def test_otm_put(self):
        """OTM put has time value."""
        put = bs_put_price(110, 100, 1.0, 0.05, 0.20)
        assert put > 0  # time value
        assert put < 100  # bounded


class TestBSGreeks:
    """Test Greek calculations."""

    def test_atm_delta(self):
        """ATM call delta ≈ 0.5 (slightly above due to drift)."""
        greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert 0.5 < greeks["delta"] < 0.7

    def test_put_delta_negative(self):
        """Put delta should be negative."""
        greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert greeks["delta"] < 0

    def test_call_put_delta_relation(self):
        """delta_call - delta_put = 1."""
        call_greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        put_greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert abs(call_greeks["delta"] - put_greeks["delta"] - 1.0) < 1e-10

    def test_gamma_positive(self):
        """Gamma is always positive (same for calls and puts)."""
        greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert greeks["gamma"] > 0

    def test_vega_positive(self):
        """Vega is always positive (more vol = more option value)."""
        greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert greeks["vega"] > 0

    def test_theta_negative(self):
        """Theta for ATM call is negative (time decay)."""
        greeks = bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert greeks["theta"] < 0


class TestBSImpliedVol:
    """Test IV solver convergence."""

    def test_round_trip(self):
        """Price → IV → Price should round-trip exactly."""
        S, K, T, r, sigma = 100, 105, 0.5, 0.05, 0.25
        price = bs_call_price(S, K, T, r, sigma)
        iv = bs_implied_vol(price, S, K, T, r, "call")
        assert iv is not None
        assert abs(iv - sigma) < 1e-6, f"IV round-trip failed: {iv} vs {sigma}"

    def test_round_trip_put(self):
        """Put IV round-trip."""
        S, K, T, r, sigma = 100, 95, 1.0, 0.05, 0.30
        price = bs_put_price(S, K, T, r, sigma)
        iv = bs_implied_vol(price, S, K, T, r, "put")
        assert iv is not None
        assert abs(iv - sigma) < 1e-5

    def test_high_vol_convergence(self):
        """IV solver should handle high vol inputs."""
        price = bs_call_price(100, 100, 1.0, 0.05, 0.80)
        iv = bs_implied_vol(price, 100, 100, 1.0, 0.05, "call")
        assert iv is not None
        assert abs(iv - 0.80) < 1e-4

    def test_invalid_price_returns_none(self):
        """Price = 0 or negative should return None."""
        assert bs_implied_vol(0, 100, 100, 1.0, 0.05) is None
        assert bs_implied_vol(-1, 100, 100, 1.0, 0.05) is None


class TestVectorized:
    """Test vectorized pricing functions."""

    def test_vec_matches_scalar(self):
        """Vectorized pricing should match scalar for each element."""
        S = 100.0
        K = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        T = np.array([0.25, 0.25, 0.25, 0.25, 0.25])
        r = 0.05
        sigma = np.array([0.20, 0.20, 0.20, 0.20, 0.20])

        vec_prices = bs_call_price_vec(S, K, T, r, sigma)
        scalar_prices = np.array([bs_call_price(S, k, t, r, s) for k, t, s in zip(K, T, sigma)])

        np.testing.assert_allclose(vec_prices, scalar_prices, rtol=1e-10)

    def test_vec_iv_round_trip(self):
        """Vectorized IV should round-trip through pricing."""
        S = 100.0
        K = np.array([90.0, 100.0, 110.0])
        T = np.array([0.5, 0.5, 0.5])
        true_sigma = np.array([0.25, 0.20, 0.30])
        r = 0.05

        prices = bs_call_price_vec(S, K, T, r, true_sigma)
        ivs = bs_implied_vol_vec(prices, S, K, T, r)

        np.testing.assert_allclose(ivs, true_sigma, atol=1e-4)
