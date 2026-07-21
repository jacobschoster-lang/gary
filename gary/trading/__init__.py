"""Paper trading bot: strategies + risk rules on a simulated brokerage account.

Runs fully offline/deterministically (:class:`PaperBroker` + synthetic price
fallback). Going live is an env-gated seam (:mod:`gary.trading.robinhood`).
"""

from gary.trading.broker import Broker, PaperBroker
from gary.trading.engine import TradingBot
from gary.trading.models import BotConfig, Fill, Position, Signal
from gary.trading.optimize import candidate_configs, optimize
from gary.trading.robinhood import RobinhoodCryptoBroker, RobinhoodError
from gary.trading.robinhood_mcp import RobinhoodMcpBroker, RobinhoodMcpError
from gary.trading.store import TradingStore

__all__ = [
    "Broker",
    "PaperBroker",
    "TradingBot",
    "BotConfig",
    "Fill",
    "Position",
    "Signal",
    "TradingStore",
    "RobinhoodCryptoBroker",
    "RobinhoodError",
    "RobinhoodMcpBroker",
    "RobinhoodMcpError",
    "optimize",
    "candidate_configs",
]
