"""
EdgeFinder — Simulation Engine

Stochastic volatility models, backtesting, paper portfolio management,
and thesis lifecycle automation.

All P&L is simulated play-money. Zero real capital at risk.
This exists purely for learning and thesis validation.

Modules:
  black_scholes  — BSM baseline (the lingua franca, not the gospel)
  heston         — Heston stochastic volatility (the real deal)
  vol_surface    — IV surface construction, SVI fitting, local vol
  backtester     — Walk-forward backtesting with Monte Carlo permutation tests
  paper_portfolio — Paper position/portfolio management
  thesis_generator — Claude-powered thesis generation from signal convergence
  deep_hedging   — Deep hedging environment + policy training (Phase 5)
  memory         — Agent long-term memory consolidation + recall
"""
