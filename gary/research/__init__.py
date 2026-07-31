"""Factor research harness.

Systematically tests documented, price-based factor edges (momentum, short-term
reversal, low-volatility, trend) against buy-and-hold using the project's honest
evaluation discipline — purged walk-forward, deflated Sharpe with multiple-testing
control, and Monte Carlo — plus a compounding goal-projection tool. The point is
to find whether any durable edge survives out-of-sample after costs (and to be
honest when none does), not to manufacture a flattering backtest.
"""
