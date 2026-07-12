"""Load the single-file agent without installing OpenRappter or runtime extras."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


class BasicAgent:
    def __init__(self, name: str, metadata: dict[str, Any]):
        self.name = name
        self.metadata = metadata
        self.context: dict[str, Any] = {}

    def execute(self, **kwargs: Any) -> str:
        return self.perform(**kwargs)


openrappter = ModuleType("openrappter")
openrappter.__path__ = []  # type: ignore[attr-defined]
agents = ModuleType("openrappter.agents")
agents.__path__ = []  # type: ignore[attr-defined]
agents.__file__ = str(ROOT / "tests" / "_openrappter_stub" / "__init__.py")
basic_agent = ModuleType("openrappter.agents.basic_agent")
basic_agent.BasicAgent = BasicAgent  # type: ignore[attr-defined]

sys.modules.setdefault("openrappter", openrappter)
sys.modules.setdefault("openrappter.agents", agents)
sys.modules.setdefault("openrappter.agents.basic_agent", basic_agent)
openrappter.agents = agents

spec = importlib.util.spec_from_file_location(
    "openrappter.agents.pokemon_agent",
    ROOT / "pokemon_agent.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("Cannot load pokemon_agent.py")
pokemon_agent = importlib.util.module_from_spec(spec)
sys.modules["openrappter.agents.pokemon_agent"] = pokemon_agent
agents.pokemon_agent = pokemon_agent
spec.loader.exec_module(pokemon_agent)
