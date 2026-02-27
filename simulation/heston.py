"""
EdgeFinder — Heston Stochastic Volatility Model

Real degenerates don't run plain Black-Scholes. They build the rocket with Heston,
calibrate it to the vol surface, and test it ruthlessly so the learning stings
in the best way. Scar tissue is tuition.

THE HESTON MODEL (1993):
  dS(t) = r·S(t)·dt + √v(t)·S(t)·dW₁(t)          (stock price)
  dv(t) = κ·(θ - v(t))·dt + σᵥ·√v(t)·dW₂(t)       (variance process)
  corr(dW₁, dW₂) = ρ

  Five parameters capture what BSM cannot:
    v₀    — current instantaneous variance (not constant!)
    κ     — speed of mean-reversion (how fast vol returns to θ)
    θ     — long-run variance level (the "home base")
    σᵥ    — vol-of-vol (how noisy is the variance process itself)
    ρ     — correlation between price and vol shocks (leverage effect)

  KEY INSIGHT: ρ < 0 means that when stock drops, vol rises. This is the
  "leverage effect" — the single most important empirical fact that BSM ignores.
  It's why put skew exists.

IMPLEMENTATION:
  1. Characteristic function (Albrecher et al. formulation — numerically stable)
  2. European call pricing via adaptive Gauss-Kronrod quadrature (scipy.integrate.quad)
  3. Calibration via scipy least_squares (Levenberg-Marquardt)
  4. Monte Carlo path generation via QE scheme (Andersen 2008)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from scipy import integrate, optimize

from simulation.black_scholes import bs_call_price, bs_implied_vol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Heston Parameters
# ---------------------------------------------------------------------------


@dataclass
class HestonParams:
    """The five parameters of the Heston stochastic volatility model.

    Attributes:
        v0: Initial instantaneous variance (e.g., 0.04 = 20% vol)
        kappa: Mean-reversion speed of variance (typical: 1-5)
        theta: Long-run variance (e.g., 0.04 = 20% long-run vol)
        sigma_v: Volatility of variance — "vol of vol" (typical: 0.2-0.8)
        rho: Correlation between price and variance Brownian motions (typical: -0.3 to -0.9)

    WHY THESE MATTER:
        v0: Sets today's vol level. If ATM IV is 25%, v0 ≈ 0.0625.
        kappa: High κ → vol snaps back quickly → less persistent smirks.
        theta: Where vol gravitates long-term. Determines far-expiry IV.
        sigma_v: Higher σᵥ → fatter tails, more pronounced smile.
        rho: Negative ρ → put skew. The more negative, the steeper the skew.
             This is THE parameter that drives the asymmetry in option prices.
    """

    v0: float
    kappa: float
    theta: float
    sigma_v: float
    rho: float

    def feller_condition(self) -> bool:
        """Check the Feller condition: 2·κ·θ > σᵥ².

        If this holds, the CIR variance process NEVER touches zero.
        If violated, variance can hit zero — not catastrophic (it reflects
        off zero), but the Euler scheme breaks. The QE scheme handles this.

        Most real-world calibrations violate Feller. Don't panic.
        """
        return 2 * self.kappa * self.theta > self.sigma_v**2

    def to_array(self) -> np.ndarray:
        """Convert to optimization vector [v0, kappa, theta, sigma_v, rho]."""
        return np.array([self.v0, self.kappa, self.theta, self.sigma_v, self.rho])

    @classmethod
    def from_array(cls, x: np.ndarray) -> HestonParams:
        """Reconstruct from optimization vector."""
        return cls(v0=x[0], kappa=x[1], theta=x[2], sigma_v=x[3], rho=x[4])

    def to_dict(self) -> dict:
        return {
            "v0": self.v0,
            "kappa": self.kappa,
            "theta": self.theta,
            "sigma_v": self.sigma_v,
            "rho": self.rho,
            "feller_satisfied": self.feller_condition(),
        }


# ---------------------------------------------------------------------------
# Characteristic Function
# ---------------------------------------------------------------------------


def heston_characteristic_function(
    u: complex, T: float, r: float, params: HestonParams
) -> complex:
    """Heston characteristic function φ(u) for log-price.

    MATH (Albrecher et al. formulation — avoids branch-cut issues):

    The characteristic function of ln(S_T/S_0) under risk-neutral measure:

      φ(u) = exp(i·u·r·T + C(u,T) + D(u,T)·v₀)

    where:
      d = √((ρ·σᵥ·i·u - κ)² + σᵥ²·(i·u + u²))
      g = (κ - ρ·σᵥ·i·u - d) / (κ - ρ·σᵥ·i·u + d)

      C(u,T) = (κ·θ/σᵥ²) · [(κ - ρ·σᵥ·i·u - d)·T - 2·ln((1 - g·e^(-d·T))/(1 - g))]
      D(u,T) = ((κ - ρ·σᵥ·i·u - d)/σᵥ²) · (1 - e^(-d·T))/(1 - g·e^(-d·T))

    WHY THIS MATTERS:
      The characteristic function is the Fourier transform of the risk-neutral
      probability density. Once we have φ(u), we can price ANY European payoff
      by numerical Fourier inversion. No need to solve the Heston PDE.

      This is the most elegant approach: one function → all vanilla prices.

    WHY ALBRECHER FORMULATION:
      The original Heston (1993) formulation has a discontinuity in the complex
      logarithm that causes numerical instability. Albrecher et al. (2007)
      reformulated it to avoid this. Always use this version.
    """
    v0, kappa, theta, sigma_v, rho = params.v0, params.kappa, params.theta, params.sigma_v, params.rho
    sigma_v2 = sigma_v * sigma_v

    # Intermediate calculations
    xi = kappa - rho * sigma_v * 1j * u
    d = np.sqrt(xi**2 + sigma_v2 * (1j * u + u**2))

    # Branch cut guard: ensure Re(d) >= 0 for continuous principal branch.
    # For extreme parameters (high sigma_v, rho near ±1), numpy's principal
    # sqrt may return the wrong branch. Negating d preserves |d| and fixes
    # the branch selection. Ref: Lord & Kahl (2010), §4.
    if np.real(d) < 0:
        d = -d

    # Careful with branch cut: use the formulation where g < 1
    g = (xi - d) / (xi + d)

    exp_neg_dT = np.exp(-d * T)

    # C and D coefficients
    D = ((xi - d) / sigma_v2) * (1.0 - exp_neg_dT) / (1.0 - g * exp_neg_dT)
    C = (kappa * theta / sigma_v2) * (
        (xi - d) * T - 2.0 * np.log((1.0 - g * exp_neg_dT) / (1.0 - g))
    )

    return np.exp(1j * u * r * T + C + D * v0)


# ---------------------------------------------------------------------------
# European Option Pricing
# ---------------------------------------------------------------------------


def _heston_integrand_P(
    u: float, S: float, K: float, T: float, r: float, params: HestonParams, j: int
) -> float:
    """Integrand for Heston call price.

    The call price is: C = S·P₁ - K·e^(-rT)·P₂
    where P₁ and P₂ are obtained by integrating the characteristic function.

    For j=1: P₁ uses φ(u - i) / φ(-i)  (measure change to stock numeraire)
    For j=2: P₂ uses φ(u) directly       (risk-neutral measure)
    """
    if j == 1:
        # Under stock-price numeraire
        phi = heston_characteristic_function(u - 1j, T, r, params)
        phi_neg_i = heston_characteristic_function(-1j, T, r, params)
        integrand = np.exp(-1j * u * np.log(K / S)) * phi / (1j * u * phi_neg_i)
    else:
        # Under risk-neutral measure
        phi = heston_characteristic_function(u, T, r, params)
        integrand = np.exp(-1j * u * np.log(K / S)) * phi / (1j * u)

    return integrand.real


def heston_call_price(
    S: float, K: float, T: float, r: float, params: HestonParams
) -> float:
    """Price a European call option under the Heston model.

    MATH:
      C = S·P₁ - K·e^(-rT)·P₂

    where P_j = 1/2 + (1/π)·∫₀^∞ Re[e^(-iu·ln(K/S))·φⱼ(u)/(iu)] du

    We use scipy.integrate.quad for numerical integration (adaptive
    Gauss-Kronrod). For single strikes this is more accurate and simpler
    than FFT-based methods (Carr-Madan). FFT is better when you need
    prices across many strikes simultaneously.

    Returns:
        European call price under Heston model
    """
    if T <= 0:
        return max(S - K, 0.0)

    # Integrate P1 and P2
    integral_P1, _ = integrate.quad(
        _heston_integrand_P, 0, 200, args=(S, K, T, r, params, 1),
        limit=200, epsabs=1e-10, epsrel=1e-10,
    )
    integral_P2, _ = integrate.quad(
        _heston_integrand_P, 0, 200, args=(S, K, T, r, params, 2),
        limit=200, epsabs=1e-10, epsrel=1e-10,
    )

    P1 = 0.5 + integral_P1 / math.pi
    P2 = 0.5 + integral_P2 / math.pi

    return S * P1 - K * math.exp(-r * T) * P2


def heston_put_price(
    S: float, K: float, T: float, r: float, params: HestonParams
) -> float:
    """Heston European put price via put-call parity.

    Put-call parity is model-independent, so: P = C - S + K·e^(-rT)
    """
    call = heston_call_price(S, K, T, r, params)
    return call - S + K * math.exp(-r * T)


def heston_implied_vol(
    S: float, K: float, T: float, r: float, params: HestonParams
) -> float | None:
    """Compute the BSM implied vol of a Heston-priced option.

    This is how we compare Heston to market data: price under Heston,
    then invert through BSM to get the "model IV." If calibrated well,
    model IV ≈ market IV across all strikes and expiries.
    """
    price = heston_call_price(S, K, T, r, params)
    return bs_implied_vol(price, S, K, T, r, option_type="call")


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def calibrate_heston(
    market_ivs: np.ndarray,
    strikes: np.ndarray,
    expiries: np.ndarray,
    S: float,
    r: float,
    initial_guess: HestonParams | None = None,
) -> tuple[HestonParams, float]:
    """Calibrate Heston parameters to a market implied vol surface.

    ALGORITHM:
      1. Convert market IVs to BSM call prices (the target)
      2. Define objective: sum of (model_price - market_price)² weighted by vega
      3. Use scipy.optimize.least_squares with Levenberg-Marquardt
      4. Bounds enforce: v0>0, κ>0, θ>0, σᵥ>0, -0.99<ρ<0.01

    WHY VEGA WEIGHTING:
      ATM options have high vega and are most sensitive to vol changes.
      OTM options have low vega but are most informative about tail behavior.
      Vega-weighting balances these: it normalizes the objective so that
      a 1% IV error has the same impact regardless of moneyness.

    WHY LEVENBERG-MARQUARDT:
      It's the industry standard for nonlinear least-squares. Interpolates
      between gradient descent (far from minimum) and Gauss-Newton (near minimum).
      Robust to bad initial guesses, which is important because the Heston
      objective surface is multimodal.

    Args:
        market_ivs: Implied volatilities (N,)
        strikes: Strike prices (N,)
        expiries: Time to expiry in years (N,)
        S: Current spot price
        r: Risk-free rate
        initial_guess: Starting parameters (or sensible defaults)

    Returns:
        (calibrated_params, rmse_error) — the calibrated HestonParams and fit RMSE
    """
    if initial_guess is None:
        # Sensible defaults: ATM vol for v0/theta, moderate mean-reversion,
        # typical vol-of-vol, and negative correlation (leverage effect)
        atm_var = float(np.mean(market_ivs) ** 2)
        initial_guess = HestonParams(
            v0=atm_var,
            kappa=2.0,
            theta=atm_var,
            sigma_v=0.4,
            rho=-0.7,
        )

    # Convert market IVs to BSM prices (our target)
    market_prices = np.array([
        bs_call_price(S, K, T, r, float(iv))
        for K, T, iv in zip(strikes, expiries, market_ivs)
    ])

    # Vega weights for normalization
    vega_weights = np.array([
        S * math.sqrt(T) * math.exp(-0.5 * ((math.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T)))**2) / math.sqrt(2 * math.pi)
        if T > 0 and iv > 0 else 1.0
        for K, T, iv in zip(strikes, expiries, market_ivs)
    ])
    vega_weights = np.maximum(vega_weights, 0.01)  # floor to avoid div-by-zero

    def residuals(x: np.ndarray) -> np.ndarray:
        params = HestonParams.from_array(x)
        model_prices = np.array([
            heston_call_price(S, float(K), float(T), r, params)
            for K, T in zip(strikes, expiries)
        ])
        return (model_prices - market_prices) / vega_weights

    x0 = initial_guess.to_array()

    # Parameter bounds: all positive except rho ∈ (-1, 1)
    bounds_lower = [0.001, 0.01, 0.001, 0.01, -0.999]
    bounds_upper = [2.0, 20.0, 2.0, 5.0, 0.999]

    result = optimize.least_squares(
        residuals,
        x0,
        bounds=(bounds_lower, bounds_upper),
        method="trf",  # Trust Region Reflective (handles bounds)
        max_nfev=500,
        ftol=1e-8,
        xtol=1e-8,
    )

    calibrated = HestonParams.from_array(result.x)

    # Compute RMSE in IV space (more interpretable than price space)
    model_ivs = np.array([
        heston_implied_vol(S, float(K), float(T), r, calibrated) or 0.0
        for K, T in zip(strikes, expiries)
    ])
    rmse = float(np.sqrt(np.mean((model_ivs - market_ivs) ** 2)))

    logger.info(
        "Heston calibration complete: v0=%.4f κ=%.2f θ=%.4f σᵥ=%.3f ρ=%.3f RMSE=%.4f Feller=%s",
        calibrated.v0, calibrated.kappa, calibrated.theta,
        calibrated.sigma_v, calibrated.rho, rmse,
        calibrated.feller_condition(),
    )

    return calibrated, rmse


# ---------------------------------------------------------------------------
# Monte Carlo Path Generation — QE Scheme (Andersen 2008)
# ---------------------------------------------------------------------------


def generate_heston_paths(
    S0: float,
    T: float,
    r: float,
    params: HestonParams,
    n_paths: int = 10_000,
    n_steps: int = 252,
    seed: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate Monte Carlo paths under the Heston model using QE scheme.

    WHY QE (Quadratic-Exponential) INSTEAD OF EULER-MARUYAMA:
      The variance process dv = κ(θ-v)dt + σᵥ√v·dW is a CIR process.
      Euler-Maruyama discretization can produce NEGATIVE variance when
      the Feller condition (2κθ > σᵥ²) is violated — which happens in
      most real calibrations.

      The QE scheme (Andersen 2008) avoids this by:
      1. Computing the exact first two moments of v(t+dt) | v(t)
      2. Matching these moments to either a quadratic normal or
         exponential distribution (hence "quadratic-exponential")
      3. GUARANTEEING v > 0 regardless of parameters

      Result: 10× fewer steps needed for the same accuracy vs Euler.

    ALGORITHM (simplified):
      Given v(t):
        m = θ + (v(t) - θ)·e^(-κ·dt)           # conditional mean
        s² = v(t)·σᵥ²·e^(-κ·dt)/κ·(1-e^(-κ·dt))  # + long-run term
        ψ = s²/m²                                # "shape ratio"

        if ψ ≤ 1.5:  (safe regime — use quadratic normal)
            v(t+dt) = a·(b + Z_v)²  where Z_v ~ N(0,1)
        else:  (dangerous regime — use exponential)
            v(t+dt) = sampling from shifted exponential

      Then update log-price:
        ln S(t+dt) = ln S(t) + (r - v̄/2)·dt + ρ/σᵥ·(v(t+dt) - v(t) - κθ·dt + κ·v̄·dt)
                     + √((1-ρ²)·v̄·dt)·Z_s

      where v̄ = (v(t) + v(t+dt))/2 (trapezoidal approx)

    Args:
        S0: Initial stock price
        T: Time horizon in years
        r: Risk-free rate
        params: Heston parameters
        n_paths: Number of simulation paths
        n_steps: Number of time steps per path
        seed: Random seed for reproducibility

    Returns:
        (price_paths, variance_paths) — each shape (n_paths, n_steps + 1)
        Column 0 = initial values (S0, v0)
    """
    rng = np.random.default_rng(seed)
    dt = T / n_steps

    v0, kappa, theta, sigma_v, rho = params.v0, params.kappa, params.theta, params.sigma_v, params.rho
    sigma_v2 = sigma_v**2

    # Pre-compute constants
    exp_neg_kdt = math.exp(-kappa * dt)
    kappa_dt = kappa * dt

    # Output arrays
    S = np.zeros((n_paths, n_steps + 1))
    V = np.zeros((n_paths, n_steps + 1))
    S[:, 0] = S0
    V[:, 0] = v0

    # QE threshold
    psi_crit = 1.5

    for t in range(n_steps):
        v_t = V[:, t]

        # --- QE scheme for variance ---
        # Conditional moments of v(t+dt) | v(t) under CIR
        m = theta + (v_t - theta) * exp_neg_kdt  # mean
        s2 = (
            v_t * sigma_v2 * exp_neg_kdt / kappa * (1 - exp_neg_kdt)
            + theta * sigma_v2 / (2 * kappa) * (1 - exp_neg_kdt) ** 2
        )
        s2 = np.maximum(s2, 1e-12)  # numerical floor

        psi = s2 / (m**2 + 1e-12)  # shape ratio

        # Generate uniform random numbers for the exponential branch
        U_v = rng.uniform(size=n_paths)
        Z_v = rng.standard_normal(n_paths)

        v_next = np.zeros(n_paths)

        # Quadratic-normal branch (ψ ≤ ψ_crit)
        mask_q = psi <= psi_crit
        if np.any(mask_q):
            b2 = 2.0 / psi[mask_q] - 1.0 + np.sqrt(2.0 / psi[mask_q]) * np.sqrt(
                np.maximum(2.0 / psi[mask_q] - 1.0, 0.0)
            )
            a_q = m[mask_q] / (1.0 + b2)
            v_next[mask_q] = a_q * (np.sqrt(b2) + Z_v[mask_q]) ** 2

        # Exponential branch (ψ > ψ_crit)
        mask_e = ~mask_q
        if np.any(mask_e):
            p = (psi[mask_e] - 1.0) / (psi[mask_e] + 1.0)
            beta = (1.0 - p) / (m[mask_e] + 1e-12)

            # Inverse CDF sampling
            v_next[mask_e] = np.where(
                U_v[mask_e] <= p,
                0.0,
                np.log((1.0 - p) / np.maximum(1.0 - U_v[mask_e], 1e-12)) / beta,
            )

        v_next = np.maximum(v_next, 0.0)
        V[:, t + 1] = v_next

        # --- Log-price update ---
        # Trapezoidal variance: v̄ = (v(t) + v(t+dt)) / 2
        v_bar = 0.5 * (v_t + v_next)
        v_bar = np.maximum(v_bar, 1e-12)

        # Correlated Brownian motion
        Z_s = rng.standard_normal(n_paths)

        # Exact conditional formula for log-price (Broadie-Kaya inspired)
        k0 = -rho * kappa * theta * dt / sigma_v
        k1 = 0.5 * dt * (rho * kappa / sigma_v - 0.5) - rho / sigma_v
        k2 = 0.5 * dt * (rho * kappa / sigma_v - 0.5) + rho / sigma_v
        k3 = 0.5 * dt * (1.0 - rho**2)

        log_S = np.log(S[:, t]) + r * dt + k0 + k1 * v_t + k2 * v_next + np.sqrt(k3 * v_bar) * Z_s
        S[:, t + 1] = np.exp(log_S)

    return S, V


# ---------------------------------------------------------------------------
# Heston Greeks (finite difference)
# ---------------------------------------------------------------------------


def heston_greeks(
    S: float, K: float, T: float, r: float, params: HestonParams,
    option_type: str = "call", bump: float = 0.01,
) -> dict[str, float]:
    """Compute Greeks under Heston via finite differences.

    Unlike BSM, Heston doesn't have closed-form Greeks (except delta via P1).
    Finite differences: bump each input, reprice, compute the ratio.

    This is how desks actually compute Greeks for stoch vol models.

    Args:
        bump: Relative bump size (1% by default)
    """
    price_fn = heston_call_price if option_type == "call" else heston_put_price
    base_price = price_fn(S, K, T, r, params)

    dS = S * bump
    delta = (price_fn(S + dS, K, T, r, params) - price_fn(S - dS, K, T, r, params)) / (2 * dS)
    gamma = (price_fn(S + dS, K, T, r, params) - 2 * base_price + price_fn(S - dS, K, T, r, params)) / (dS**2)

    # Theta: bump T down by 1 day
    dT = 1 / 365.0
    if T > dT:
        theta = (price_fn(S, K, T - dT, r, params) - base_price) / dT
    else:
        theta = 0.0

    # Vega: bump v0 (initial variance)
    dv = params.v0 * bump
    params_up = HestonParams(params.v0 + dv, params.kappa, params.theta, params.sigma_v, params.rho)
    params_dn = HestonParams(max(params.v0 - dv, 0.001), params.kappa, params.theta, params.sigma_v, params.rho)
    vega = (price_fn(S, K, T, r, params_up) - price_fn(S, K, T, r, params_dn)) / (2 * dv)

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "price": base_price,
    }
