"""
EdgeFinder — Volatility Surface Construction & Analysis

The volatility surface is the market's collective opinion about future
uncertainty — across all strikes and maturities. It's where Black-Scholes
breaks down most visibly, and where real edge lives.

KEY CONCEPTS:
  1. IMPLIED VOL SURFACE: A 3D object (strike × expiry → IV).
     BSM says this should be flat. It's not. The deviations tell us:
     - Skew (OTM puts more expensive) → crash fear, leverage effect
     - Smile (both wings elevated) → fat tails, jump risk
     - Term structure (near vs far) → event expectations (earnings, FOMC)

  2. SVI PARAMETERIZATION (Gatheral, 2004):
     w(k) = a + b·(ρ·(k-m) + √((k-m)² + σ²))
     where w = σ²·T is total variance, k = ln(K/F) is log-moneyness.
     Parsimonious (5 params), arbitrage-aware, industry standard.

  3. LOCAL VOLATILITY (Dupire, 1994):
     σ_local(K,T) — the unique diffusion coefficient that reproduces all
     European option prices. Derived from the implied vol surface.

  4. ARBITRAGE DETECTION:
     - Calendar spread: total variance must increase with T
     - Butterfly: call prices must be convex in K
     If these are violated, there's a riskless profit opportunity.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from scipy import interpolate, optimize

from simulation.black_scholes import bs_call_price, bs_implied_vol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IV Surface Construction
# ---------------------------------------------------------------------------


def build_iv_surface(
    options_df: pd.DataFrame,
    S: float,
    r: float,
    min_volume: int = 10,
    min_oi: int = 100,
) -> pd.DataFrame:
    """Construct an implied volatility surface from raw options chain data.

    Takes the raw OptionsChain data and produces a clean grid of IVs
    indexed by moneyness (K/S) and time to expiry.

    Filtering:
      - Remove options with volume < min_volume (illiquid, stale quotes)
      - Remove options with OI < min_oi (no real market)
      - Use mid price (bid+ask)/2 for IV computation
      - Exclude deep ITM/OTM (moneyness outside 0.7-1.3)

    Args:
        options_df: DataFrame with columns: strike, expiration, call_put,
                    bid, ask, volume, open_interest, implied_vol
        S: Current spot price
        r: Risk-free rate
        min_volume: Minimum volume filter
        min_oi: Minimum open interest filter

    Returns:
        DataFrame with columns: strike, expiry_years, moneyness, implied_vol, call_put
    """
    df = options_df.copy()

    # Filter for quality
    df = df[(df["volume"] >= min_volume) & (df["open_interest"] >= min_oi)]

    if df.empty:
        logger.warning("No options pass quality filters (vol>=%d, OI>=%d)", min_volume, min_oi)
        return pd.DataFrame(columns=["strike", "expiry_years", "moneyness", "implied_vol", "call_put"])

    # Compute mid price
    df["mid_price"] = (df["bid"] + df["ask"]) / 2
    df = df[df["mid_price"] > 0]

    # Compute moneyness
    df["moneyness"] = df["strike"].astype(float) / S

    # Filter reasonable moneyness range
    df = df[(df["moneyness"] >= 0.7) & (df["moneyness"] <= 1.3)]

    # If implied_vol not provided, compute it
    if "implied_vol" not in df.columns or df["implied_vol"].isna().all():
        ivs = []
        for _, row in df.iterrows():
            iv = bs_implied_vol(
                float(row["mid_price"]),
                S,
                float(row["strike"]),
                float(row["expiry_years"]),
                r,
                option_type=row["call_put"],
            )
            ivs.append(iv)
        df["implied_vol"] = ivs

    # Drop rows where IV computation failed
    df = df.dropna(subset=["implied_vol"])
    df = df[df["implied_vol"] > 0.01]  # remove nonsensical IVs

    return df[["strike", "expiry_years", "moneyness", "implied_vol", "call_put"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# SVI Parameterization (Gatheral)
# ---------------------------------------------------------------------------


def _svi_total_variance(k: np.ndarray, a: float, b: float, rho: float, m: float, sigma: float) -> np.ndarray:
    """SVI formula for total variance w(k).

    MATH:
      w(k) = a + b·(ρ·(k - m) + √((k - m)² + σ²))

    Parameters:
      a: overall level of variance (vertical shift)
      b: slope/angle of the wings (how steep the smile)
      ρ: rotation/tilt (skew direction, -1 to 1)
      m: translation (horizontal shift of the minimum)
      σ: smoothness (how rounded the vertex is)

    WHY SVI:
      Gatheral showed that SVI is the natural parameterization for the vol
      surface because:
      1. It matches the large-strike asymptotics of BSM exactly
      2. It's arbitrage-free when properly constrained
      3. Just 5 parameters per maturity slice (vs. spline coefficients)
      4. It can be efficiently calibrated via quasi-Newton methods
    """
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma**2))


def fit_svi(
    ivs: np.ndarray,
    strikes: np.ndarray,
    forward: float,
    T: float,
) -> dict:
    """Fit Gatheral's SVI parameterization to a single maturity slice.

    Takes implied vols and strikes for ONE expiry and fits the 5 SVI params.

    Args:
        ivs: Implied volatilities for this expiry
        strikes: Strike prices
        forward: Forward price F = S·e^(rT)
        T: Time to expiry in years

    Returns:
        dict with keys: a, b, rho, m, sigma, rmse, total_var_fit
    """
    # Convert to log-moneyness and total variance
    k = np.log(strikes / forward)
    w_market = ivs**2 * T  # total variance = σ²·T

    def objective(params):
        a, b, rho, m, sigma = params
        w_model = _svi_total_variance(k, a, b, rho, m, sigma)
        return w_model - w_market

    # Initial guess
    atm_var = float(np.interp(0.0, k, w_market))
    x0 = [atm_var, 0.1, -0.3, 0.0, 0.1]

    # Bounds: a ∈ R, b > 0, -1 < ρ < 1, m ∈ R, σ > 0
    bounds_lower = [-1.0, 0.001, -0.999, -2.0, 0.001]
    bounds_upper = [2.0, 5.0, 0.999, 2.0, 5.0]

    result = optimize.least_squares(
        objective, x0,
        bounds=(bounds_lower, bounds_upper),
        method="trf",
        max_nfev=200,
    )

    a, b, rho, m, sigma = result.x

    # Compute fit quality
    w_fit = _svi_total_variance(k, a, b, rho, m, sigma)
    iv_fit = np.sqrt(w_fit / T)
    rmse = float(np.sqrt(np.mean((iv_fit - ivs) ** 2)))

    return {
        "a": float(a),
        "b": float(b),
        "rho": float(rho),
        "m": float(m),
        "sigma": float(sigma),
        "rmse": rmse,
        "T": T,
    }


def fit_svi_surface(
    surface_df: pd.DataFrame,
    S: float,
    r: float,
) -> list[dict]:
    """Fit SVI to each expiry slice in the vol surface.

    Returns a list of SVI parameter sets, one per expiry.
    """
    results = []
    for T, group in surface_df.groupby("expiry_years"):
        if len(group) < 3:
            continue
        T = float(T)
        forward = S * math.exp(r * T)
        try:
            svi_params = fit_svi(
                group["implied_vol"].values,
                group["strike"].values.astype(float),
                forward,
                T,
            )
            results.append(svi_params)
        except Exception as e:
            logger.warning("SVI fit failed for T=%.3f: %s", T, e)
    return results


# ---------------------------------------------------------------------------
# Surface Interpolation
# ---------------------------------------------------------------------------


def interpolate_surface(
    surface_df: pd.DataFrame,
    K: float,
    T: float,
    method: str = "cubic",
) -> float | None:
    """Interpolate the IV surface at a specific (K, T) point.

    Uses 2D cubic spline interpolation in (log-moneyness, T) space.
    Log-moneyness is more natural for interpolation because the smile
    is roughly symmetric in that coordinate.

    Args:
        surface_df: DataFrame with moneyness, expiry_years, implied_vol
        K: Target strike
        T: Target time to expiry
        method: Interpolation method ('cubic', 'linear')

    Returns:
        Interpolated implied vol, or None if out of range
    """
    if surface_df.empty:
        return None

    moneyness = surface_df["moneyness"].values
    expiries = surface_df["expiry_years"].values
    ivs = surface_df["implied_vol"].values

    # Need at least 4 points for cubic
    if len(ivs) < 4:
        method = "linear"

    try:
        interp = interpolate.griddata(
            points=np.column_stack([np.log(moneyness), expiries]),
            values=ivs,
            xi=np.array([[np.log(K / surface_df.attrs.get("S", K)), T]]),
            method=method,
        )
        result = float(interp[0])
        if np.isnan(result):
            return None
        return result
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Arbitrage Detection
# ---------------------------------------------------------------------------


def detect_arbitrage(surface_df: pd.DataFrame, S: float, r: float) -> list[dict]:
    """Check the IV surface for static arbitrage violations.

    Two key conditions:

    1. CALENDAR SPREAD ARBITRAGE:
       Total variance w(K, T) = σ²(K,T)·T must be NON-DECREASING in T
       for any fixed K. If w(K, T₁) > w(K, T₂) for T₁ < T₂, you can
       buy the near-dated and sell the far-dated for riskless profit.

       Intuition: more time = more uncertainty = more total variance.
       Always. If the market violates this, something is mispriced.

    2. BUTTERFLY ARBITRAGE:
       The call price C(K) must be CONVEX in K (i.e., d²C/dK² ≥ 0).
       Equivalently, for three strikes K₁ < K₂ < K₃:
         C(K₂) ≤ (K₃-K₂)/(K₃-K₁)·C(K₁) + (K₂-K₁)/(K₃-K₁)·C(K₃)

       If violated, you can sell the butterfly spread for riskless profit.
       This means the implied probability density has gone NEGATIVE —
       which is economically impossible.

    Returns:
        List of arbitrage violation dicts with type, location, magnitude
    """
    violations = []

    # --- Calendar Spread Check ---
    for _, group in surface_df.groupby("strike"):
        if len(group) < 2:
            continue
        group = group.sort_values("expiry_years")
        ivs = group["implied_vol"].values
        Ts = group["expiry_years"].values.astype(float)
        total_vars = ivs**2 * Ts

        for i in range(len(total_vars) - 1):
            if total_vars[i] > total_vars[i + 1] + 1e-6:
                violations.append({
                    "type": "calendar_spread",
                    "strike": float(group.iloc[i]["strike"]),
                    "T_near": float(Ts[i]),
                    "T_far": float(Ts[i + 1]),
                    "w_near": float(total_vars[i]),
                    "w_far": float(total_vars[i + 1]),
                    "magnitude": float(total_vars[i] - total_vars[i + 1]),
                })

    # --- Butterfly Check ---
    for T, group in surface_df.groupby("expiry_years"):
        T = float(T)
        if len(group) < 3:
            continue
        group = group.sort_values("strike")
        strikes = group["strike"].values.astype(float)
        ivs = group["implied_vol"].values

        # Compute call prices
        prices = np.array([
            bs_call_price(S, float(K), T, r, float(iv))
            for K, iv in zip(strikes, ivs)
        ])

        # Check convexity: C(K_i) - 2*C(K_{i+1}) + C(K_{i+2}) >= 0
        for i in range(len(prices) - 2):
            K1, K2, K3 = strikes[i], strikes[i + 1], strikes[i + 2]
            C1, C2, C3 = prices[i], prices[i + 1], prices[i + 2]

            # Weighted butterfly value
            dK1 = K2 - K1
            dK2 = K3 - K2
            dK = K3 - K1
            butterfly = C1 * dK2 / dK - C2 + C3 * dK1 / dK

            if butterfly < -1e-4:
                violations.append({
                    "type": "butterfly",
                    "expiry_years": T,
                    "K1": float(K1),
                    "K2": float(K2),
                    "K3": float(K3),
                    "butterfly_value": float(butterfly),
                    "magnitude": float(abs(butterfly)),
                })

    return violations


# ---------------------------------------------------------------------------
# Local Volatility (Dupire)
# ---------------------------------------------------------------------------


def compute_local_vol(
    iv_surface: pd.DataFrame,
    S: float,
    r: float,
    dK_frac: float = 0.01,
    dT_frac: float = 0.01,
) -> pd.DataFrame:
    """Compute local volatility surface via Dupire's formula.

    MATH (Dupire, 1994):
      The unique diffusion coefficient that reproduces all European prices:

      σ²_local(K, T) = (∂w/∂T) / (1 - k/w · ∂w/∂k + 1/4·(-1/4 - 1/w + k²/w²)·(∂w/∂k)² + 1/2·∂²w/∂k²)

    where w = σ²·T is total variance and k = ln(K/F) is log-moneyness.

    WHY LOCAL VOL MATTERS:
      Local vol is the bridge between implied vol and actual dynamics.
      - BSM: σ_local = constant (wrong)
      - Local vol: σ_local(K,T) varies, reproduces all vanillas exactly
      - Heston: σ_local emerges from the stochastic vol dynamics

      If you price an exotic (barrier, Asian, etc.) and the model matters,
      local vol tells you what the market-consistent diffusion looks like.
      But beware: local vol has known issues with forward smile dynamics
      (it flattens the smile for forward-starting options).

    Uses finite differences on the IV surface to approximate derivatives.
    """
    if iv_surface.empty:
        return pd.DataFrame(columns=["strike", "expiry_years", "local_vol"])

    results = []
    for _, row in iv_surface.iterrows():
        K = float(row["strike"])
        T = float(row["expiry_years"])
        iv = float(row["implied_vol"])

        if T < 0.01:
            continue

        w = iv**2 * T
        F = S * math.exp(r * T)
        k = math.log(K / F)

        # Numerical derivatives via surface interpolation
        dK = K * dK_frac
        dT = max(T * dT_frac, 1 / 365.0)

        # dw/dT
        iv_T_up = _lookup_iv(iv_surface, K, T + dT)
        iv_T_dn = _lookup_iv(iv_surface, K, max(T - dT, 0.01))
        if iv_T_up is None or iv_T_dn is None:
            continue
        dw_dT = (iv_T_up**2 * (T + dT) - iv_T_dn**2 * max(T - dT, 0.01)) / (2 * dT)

        # dw/dk
        iv_K_up = _lookup_iv(iv_surface, K + dK, T)
        iv_K_dn = _lookup_iv(iv_surface, K - dK, T)
        if iv_K_up is None or iv_K_dn is None:
            continue
        k_up = math.log((K + dK) / F)
        k_dn = math.log((K - dK) / F)
        w_up = iv_K_up**2 * T
        w_dn = iv_K_dn**2 * T
        dw_dk = (w_up - w_dn) / (k_up - k_dn)

        # d2w/dk2
        d2w_dk2 = (w_up - 2 * w + w_dn) / ((k_up - k_dn) / 2) ** 2

        # Dupire formula
        denom = 1 - k / w * dw_dk + 0.25 * (-0.25 - 1 / w + k**2 / w**2) * dw_dk**2 + 0.5 * d2w_dk2
        if denom <= 0 or dw_dT <= 0:
            continue

        local_var = dw_dT / denom
        if local_var > 0:
            results.append({
                "strike": K,
                "expiry_years": T,
                "local_vol": math.sqrt(local_var),
            })

    return pd.DataFrame(results)


def _lookup_iv(surface_df: pd.DataFrame, K: float, T: float) -> float | None:
    """Find the nearest IV on the surface for a given (K, T).

    Simple nearest-neighbor lookup. For production, use the interpolate_surface
    function, but for finite differences this is fast and adequate.
    """
    if surface_df.empty:
        return None

    dists = (surface_df["strike"].astype(float) - K) ** 2 / K**2 + (surface_df["expiry_years"].astype(float) - T) ** 2
    idx = dists.idxmin()

    # Only return if close enough (within 5% moneyness and 0.05 years)
    row = surface_df.loc[idx]
    if abs(float(row["strike"]) - K) / K > 0.05 or abs(float(row["expiry_years"]) - T) > 0.05:
        return None

    return float(row["implied_vol"])


# ---------------------------------------------------------------------------
# Surface Visualization Helpers
# ---------------------------------------------------------------------------


def surface_to_grid(
    surface_df: pd.DataFrame,
) -> dict:
    """Convert surface DataFrame to a JSON-serializable grid for dashboard.

    Returns:
        {
            "moneyness": [0.8, 0.9, 1.0, 1.1, 1.2],
            "expiries": [0.083, 0.25, 0.5, 1.0],
            "ivs": [[iv_00, iv_01, ...], [iv_10, ...], ...],
            "atm_iv": float,
            "skew_25d": float,
        }
    """
    if surface_df.empty:
        return {"moneyness": [], "expiries": [], "ivs": [], "atm_iv": None, "skew_25d": None}

    # Pivot to grid
    pivot = surface_df.pivot_table(
        index="moneyness", columns="expiry_years", values="implied_vol", aggfunc="mean"
    )

    moneyness = pivot.index.tolist()
    expiries = [float(c) for c in pivot.columns]
    ivs = pivot.values.tolist()

    # ATM IV (moneyness closest to 1.0)
    atm_idx = min(range(len(moneyness)), key=lambda i: abs(moneyness[i] - 1.0))
    atm_iv = float(np.nanmean(pivot.iloc[atm_idx]))

    # 25-delta skew: difference between 25d put IV and 25d call IV
    # Approximate: moneyness ~0.92 (25d put) vs ~1.08 (25d call)
    put_25d_idx = min(range(len(moneyness)), key=lambda i: abs(moneyness[i] - 0.92))
    call_25d_idx = min(range(len(moneyness)), key=lambda i: abs(moneyness[i] - 1.08))
    skew_25d = float(np.nanmean(pivot.iloc[put_25d_idx]) - np.nanmean(pivot.iloc[call_25d_idx]))

    return {
        "moneyness": [float(m) for m in moneyness],
        "expiries": expiries,
        "ivs": [[float(v) if not np.isnan(v) else None for v in row] for row in ivs],
        "atm_iv": atm_iv,
        "skew_25d": skew_25d,
    }
