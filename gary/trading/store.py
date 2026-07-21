"""Local JSON persistence for the paper trading account.

Saves the bot config + paper broker state so the simulated portfolio survives
restarts. Path is configurable via ``GARY_TRADING_FILE`` and lives under the
gitignored ``finance_data/`` dir, matching the finance module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from gary.trading.broker import PaperBroker
from gary.trading.models import BotConfig

_DEFAULT_PATH = os.environ.get("GARY_TRADING_FILE", "finance_data/trading.json")


class TradingStore:
    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> tuple[BotConfig, PaperBroker]:
        if not self.path.exists():
            config = BotConfig()
            return config, PaperBroker(cash=config.starting_cash)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = BotConfig()
            return config, PaperBroker(cash=config.starting_cash)
        config = BotConfig.from_dict(data.get("config"))
        broker = PaperBroker.deserialize(data.get("broker"))
        return config, broker

    def save(
        self, config: BotConfig, broker: PaperBroker, extra: dict[str, Any] | None = None
    ) -> None:
        payload: dict[str, Any] = {"config": config.to_dict(), "broker": broker.serialize()}
        if extra:
            payload.update(extra)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def reset(self, config: BotConfig | None = None) -> tuple[BotConfig, PaperBroker]:
        config = config or BotConfig()
        broker = PaperBroker(cash=config.starting_cash)
        self.save(config, broker)
        return config, broker
