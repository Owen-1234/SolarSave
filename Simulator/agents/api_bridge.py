from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .coordination_loop import CoordinationLoop
from .types import EpisodeConfig


def build_config(payload: dict[str, Any] | None = None) -> EpisodeConfig:
    payload = payload or {}
    return EpisodeConfig(
        start_step=int(payload.get("start_step", 0)),
        steps=int(payload.get("steps", 24)),
        reward_share=float(payload.get("reward_share", 0.20)),
        demand_multiplier=float(payload.get("demand_multiplier", 1.0)),
        planner_policy=str(payload.get("planner_policy", "balanced")),
        mode=str(payload.get("mode", "connected_demo")),
        max_agents=payload.get("max_agents"),
    )


def loop_status(loop: CoordinationLoop | None) -> dict[str, Any]:
    if loop is None:
        return {"status": "not_initialized"}
    return {
        "status": "ready",
        "episode_id": loop.config.episode_id,
        "mode": loop.config.mode,
        "agents": len(loop.agents),
        "dataset": {
            "data_dir": str(loop.config.data_dir),
            "nodes": len(loop.environment.dataset.nodes),
            "generation_rows": len(loop.environment.dataset.generation),
            "fdia_rows": int(loop.environment.dataset.generation["fdia_detected"].sum()),
            "timestamps": len(loop.environment.dataset.timestamps),
            "cities": sorted(loop.environment.dataset.nodes["city"].unique().tolist()),
        },
        "last_market_summary": None if loop.last_market_summary is None else loop.last_market_summary.__dict__,
    }


def recent_events(output_dir: Path, limit: int = 100, event_file: str = "eiot_event_log.csv") -> list[dict[str, Any]]:
    path = Path(output_dir) / event_file
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    rows = frame.tail(limit).to_dict("records")
    for row in rows:
        for key in ("physical_state", "reported_state", "market_feedback"):
            if isinstance(row.get(key), str) and row[key]:
                try:
                    row[key] = json.loads(row[key])
                except json.JSONDecodeError:
                    pass
    return rows


def audit_events(output_dir: Path, limit: int = 100) -> list[dict[str, Any]]:
    return recent_events(output_dir, limit=limit, event_file="audit_logs.csv")


def market_summary(output_dir: Path, limit: int = 24) -> list[dict[str, Any]]:
    path = Path(output_dir) / "agent_market_summary.csv"
    if not path.exists():
        return []
    return pd.read_csv(path).tail(limit).to_dict("records")
