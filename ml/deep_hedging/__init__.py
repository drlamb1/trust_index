"""
EdgeFinder — Deep Hedging ML Pipeline (Buehler et al. 2019)

Three modules:
  policy_network.py  — PyTorch policy net (local training only)
  training.py        — Full training loop with Heston path generation
  inference.py       — Pure NumPy inference (deployed on Railway)
"""
