"""
EdgeFinder — Black-Scholes Model (The Baseline, Not the Gospel)

Black-Scholes is wrong — constant vol, log-normal returns, no jumps.
Every practitioner knows this. But it's the COORDINATE SYSTEM of options
markets. When traders quote "implied vol," they're inverting BSM.

We implement it here as our baseline for three reasons:
  1. Sanity checks — Heston should converge to BSM as sigma_v → 0
  2. Comparison — deep hedging should outperform BSM delta hedging
  3. IV computation — we need BSM IV to calibrate stochastic vol models

MATH OVERVIEW:
  Under BSM assumptions (geometric Brownian motion, constant vol σ):
    dS = μ·S·dt + σ·S·dW

  The risk-neutral pricing formula for a European call:
    C = S·N(d₁) - K·e^(-rT)·N(d₂)
  where:
    d₁ = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
    d₂ = d₁ - σ·√T
    N(·) = standard normal CDF

  Greeks are analytical derivatives of this formula.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Core pricing
# ---------------------------------------------------------------------------


def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price.

    Args:
        S: Current spot price
        K: Strike price
        T: Time to expiry in years (e.g., 0.25 = 3 months)
        r: Risk-free rate (annualized, continuous compounding)
        sigma: Volatility (annualized, e.g., 0.20 = 20%)

    Returns:
        Call option price

    Math:
        C = S·N(d₁) - K·e^(-rT)·N(d₂)
        d₁ = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
        d₂ = d₁ - σ·√T

    Why this matters:
        This is the formula that changed finance. Fischer Black and Myron Scholes
        showed that under certain assumptions, the price of an option depends ONLY
        on five observable quantities. No expected return (μ) needed — it cancels
        out through delta hedging. This is risk-neutral pricing in action.
    """
    if T <= 0:
        return max(S - K, 0.0)
    if sigma <= 0:
        return max(S - K * math.exp(-r * T), 0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European put price via put-call parity.

    Math:
        P = K·e^(-rT)·N(-d₂) - S·N(-d₁)

    Or equivalently via put-call parity:
        P = C - S + K·e^(-rT)

    Why put-call parity matters:
        It's model-independent — it holds regardless of whether BSM assumptions
        are correct. If put-call parity is violated, there's a riskless arbitrage.
        Any options model MUST satisfy it, or it's broken.
    """
    if T <= 0:
        return max(K - S, 0.0)
    if sigma <= 0:
        return max(K * math.exp(-r * T) - S, 0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# ---------------------------------------------------------------------------
# Greeks — the sensitivities that drive hedging
# ---------------------------------------------------------------------------


def bs_greeks(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call"
) -> dict[str, float]:
    """Compute all BSM Greeks analytically.

    Returns:
        dict with: delta, gamma, theta, vega, rho

    Why Greeks matter:
        Greeks tell you HOW your option price changes when inputs move.
        - Delta: exposure to underlying price (hedge ratio)
        - Gamma: rate of change of delta (convexity)
        - Theta: daily time decay (the price of holding)
        - Vega: exposure to volatility changes (the big one for vol traders)
        - Rho: exposure to interest rate changes (usually small)

    Math:
        delta_call = N(d₁)           |  delta_put = N(d₁) - 1
        gamma = φ(d₁) / (S·σ·√T)    |  same for calls and puts
        theta_call = -S·φ(d₁)·σ/(2√T) - r·K·e^(-rT)·N(d₂)
        vega = S·φ(d₁)·√T           |  same for calls and puts
        rho_call = K·T·e^(-rT)·N(d₂)
        where φ(·) = standard normal PDF
    """
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        return {
            "delta": 1.0 if intrinsic > 0 and option_type == "call" else (-1.0 if intrinsic > 0 else 0.0),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    phi_d1 = norm.pdf(d1)  # standard normal PDF at d1
    discount = math.exp(-r * T)

    # Gamma and vega are the same for calls and puts
    gamma = phi_d1 / (S * sigma * sqrt_T)
    # Vega: per 1 unit change in sigma (multiply by 0.01 for per-1% vol move)
    vega = S * phi_d1 * sqrt_T

    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (
            -S * phi_d1 * sigma / (2 * sqrt_T)
            - r * K * discount * norm.cdf(d2)
        )
        rho = K * T * discount * norm.cdf(d2)
    else:
        delta = norm.cdf(d1) - 1.0
        theta = (
            -S * phi_d1 * sigma / (2 * sqrt_T)
            + r * K * discount * norm.cdf(-d2)
        )
        rho = -K * T * discount * norm.cdf(-d2)

    # Theta is per year; convert to per day for practical use
    theta_per_day = theta / 365.0

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta_per_day,
        "vega": vega,
        "rho": rho,
    }


# ---------------------------------------------------------------------------
# Implied Volatility — inverting the BSM formula
# ---------------------------------------------------------------------------


def bs_implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = "call",
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float | None:
    """Newton-Raphson solver for BSM implied volatility.

    Given a market price, find the σ that makes BSM(σ) = market_price.
    Converges in ~5 iterations for reasonable inputs.

    Args:
        market_price: Observed option price
        S, K, T, r: BSM inputs
        option_type: "call" or "put"
        tol: Convergence tolerance
        max_iter: Max Newton-Raphson iterations

    Returns:
        Implied volatility (annualized), or None if no convergence

    Why this matters:
        Implied vol IS the market's language. When a trader says "NVDA 30-delta
        puts are trading at 35 vol," they mean: "the market price of those puts,
        when inverted through BSM, yields σ = 0.35." The IV surface (strike × expiry
        → IV) captures everything BSM gets wrong — skew, term structure, smile.
        Our job is to model that surface, not pretend it's flat.

    Algorithm:
        Newton-Raphson: σ_{n+1} = σ_n - (BSM(σ_n) - market_price) / vega(σ_n)
        We use vega as the derivative because ∂C/∂σ = vega.
        Initial guess: Brenner-Subrahmanyam approximation σ₀ ≈ √(2π/T) · C/S
    """
    if T <= 0 or market_price <= 0:
        return None

    price_fn = bs_call_price if option_type == "call" else bs_put_price

    # Check bounds: price must be between intrinsic and S (or K for puts)
    intrinsic = max(S - K * math.exp(-r * T), 0.0) if option_type == "call" else max(K * math.exp(-r * T) - S, 0.0)
    if market_price < intrinsic - tol:
        return None

    # Brenner-Subrahmanyam initial guess
    sigma = math.sqrt(2 * math.pi / T) * market_price / S
    sigma = max(0.01, min(sigma, 5.0))  # clamp to reasonable range

    for _ in range(max_iter):
        price = price_fn(S, K, T, r, sigma)
        greeks = bs_greeks(S, K, T, r, sigma, option_type)
        vega = greeks["vega"]

        if abs(vega) < 1e-12:
            # Vega too small — can't converge (deep ITM/OTM)
            break

        diff = price - market_price
        if abs(diff) < tol:
            return sigma

        sigma -= diff / vega
        sigma = max(0.001, min(sigma, 10.0))  # guard rails

    return sigma  # return best estimate even if not fully converged


# ---------------------------------------------------------------------------
# Vectorized pricing for calibration workloads
# ---------------------------------------------------------------------------


def bs_call_price_vec(
    S: float,
    K: np.ndarray,
    T: np.ndarray,
    r: float,
    sigma: np.ndarray,
) -> np.ndarray:
    """Vectorized BSM call pricing for arrays of strikes/expiries/vols.

    Used by Heston calibration to rapidly compute BSM prices for many
    (K, T, σ) combinations simultaneously.
    """
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def bs_implied_vol_vec(
    market_prices: np.ndarray,
    S: float,
    K: np.ndarray,
    T: np.ndarray,
    r: float,
    option_type: str = "call",
    tol: float = 1e-6,
    max_iter: int = 50,
) -> np.ndarray:
    """Vectorized IV solver using Newton-Raphson on arrays.

    Handles the common calibration case: given N market prices with different
    (K, T) pairs, find all N implied vols simultaneously. Much faster than
    calling the scalar version N times.
    """
    n = len(market_prices)
    sigma = np.full(n, 0.20)  # initial guess: 20% vol

    for _ in range(max_iter):
        sqrt_T = np.sqrt(T)
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        if option_type == "call":
            prices = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            prices = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

        vega = S * norm.pdf(d1) * sqrt_T

        diff = prices - market_prices
        converged = np.abs(diff) < tol
        if np.all(converged):
            break

        # Only update unconverged entries
        update_mask = (~converged) & (np.abs(vega) > 1e-12)
        sigma[update_mask] -= diff[update_mask] / vega[update_mask]
        sigma = np.clip(sigma, 0.001, 10.0)

    return sigma
