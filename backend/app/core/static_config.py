"""Static, non-secret configuration loaded from ``config/*.json``.

Configuration rule for the whole repository:

* ``.env`` / process env holds ONLY the network mode (``QMA_NETWORK_MODE``), secrets and
  deployment wiring (service URLs, database, data directory, platform-injected values,
  operational kill switches).
* ``config/networks.json`` holds per-network public chain data (chain id, RPC, contract
  addresses) selected by ``QMA_NETWORK_MODE``.
* ``config/app.json`` holds network-independent business configuration (prices, TTLs,
  public wallet addresses, rate limits, feature toggles).

This module intentionally imports nothing from ``backend`` so it can be used from any
layer (including ``paid_intelligence_kit``) without import cycles. Read values through
:func:`app_setting` at call time when tests need to override them with
``monkeypatch.setitem(APP[section], key, value)``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"


def _load_json(file_name: str) -> dict[str, Any]:
    path = CONFIG_DIR / file_name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


APP: dict[str, Any] = _load_json("app.json")
NETWORKS: dict[str, Any] = _load_json("networks.json")


def app_setting(*keys: str) -> Any:
    """Return ``APP[keys[0]][keys[1]]...``; raises ``KeyError`` for unknown keys (no silent defaults)."""
    node: Any = APP
    for key in keys:
        node = node[key]
    return node
