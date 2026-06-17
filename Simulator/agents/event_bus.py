from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .types import AgentEvent


EVENT_COLUMNS = [
    "episode_id",
    "step",
    "timestamp",
    "agent_id",
    "agent_type",
    "event_type",
    "physical_state",
    "reported_state",
    "verification_result",
    "planner_action",
    "on_chain_action",
    "tx_hash",
    "market_feedback",
    "latency_ms",
    "record_hash",
    "previous_hash",
]


class EventBus:
    """Append-only event log with a hash chain for EIoT auditability."""

    def __init__(self, output_dir: Path, event_filename: str = "eiot_event_log.csv") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.event_path = self.output_dir / event_filename
        self.audit_path = self.output_dir / "audit_logs.csv"
        self.connected_path = self.output_dir / "connected_system_trace.csv"
        self.previous_hash = "GENESIS"
        self.events: list[AgentEvent] = []
        self._reset_files()

    def _reset_files(self) -> None:
        for path in (self.event_path, self.audit_path, self.connected_path):
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=EVENT_COLUMNS)
                writer.writeheader()

    def emit(self, event: AgentEvent, audit: bool = False, connected: bool = False) -> AgentEvent:
        payload = asdict(event)
        payload["previous_hash"] = self.previous_hash
        payload["record_hash"] = self._hash_payload(payload)
        self.previous_hash = payload["record_hash"]

        stored = AgentEvent(**payload)
        self.events.append(stored)
        self._append(self.event_path, stored)
        if audit:
            self._append(self.audit_path, stored)
        if connected:
            self._append(self.connected_path, stored)
        return stored

    def _append(self, path: Path, event: AgentEvent) -> None:
        row = event.to_row()
        for key in ("physical_state", "reported_state", "market_feedback"):
            row[key] = json.dumps(row[key], sort_keys=True)
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=EVENT_COLUMNS)
            writer.writerow(row)

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        clean = dict(payload)
        clean["record_hash"] = ""
        encoded = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return [event.to_row() for event in self.events[-limit:]]
