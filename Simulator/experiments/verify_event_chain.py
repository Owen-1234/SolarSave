from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from Simulator.agents.event_bus import EVENT_COLUMNS
from Simulator.agents.types import DEFAULT_EXPERIMENT_DIR
from Simulator.experiments.common import ensure_output_dir


JSON_COLUMNS = {"physical_state", "reported_state", "market_feedback"}


def _parse_json_cell(value: str) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _canonical_payload(row: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in EVENT_COLUMNS:
        value = row.get(key, "")
        if key in JSON_COLUMNS:
            payload[key] = _parse_json_cell(value)
        elif key == "step":
            payload[key] = int(value)
        elif key == "latency_ms":
            payload[key] = float(value)
        else:
            payload[key] = value
    return payload


def _hash_payload(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean["record_hash"] = ""
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_event_chain(event_path: Path = DEFAULT_EXPERIMENT_DIR / "eiot_event_log.csv") -> dict[str, Any]:
    event_path = Path(event_path)
    if not event_path.exists():
        raise FileNotFoundError(event_path)

    previous_hash = "GENESIS"
    rows_checked = 0
    first_error = ""
    event_types: set[str] = set()
    last_hash = "GENESIS"

    with event_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing_columns = [column for column in EVENT_COLUMNS if column not in (reader.fieldnames or [])]
        if missing_columns:
            first_error = f"missing_columns:{','.join(missing_columns)}"
        else:
            for index, row in enumerate(reader, start=1):
                rows_checked += 1
                payload = _canonical_payload(row)
                event_types.add(str(payload["event_type"]))
                expected_hash = _hash_payload(payload)
                if payload["previous_hash"] != previous_hash:
                    first_error = f"row_{index}_previous_hash_mismatch"
                    break
                if payload["record_hash"] != expected_hash:
                    first_error = f"row_{index}_record_hash_mismatch"
                    break
                previous_hash = str(payload["record_hash"])
                last_hash = previous_hash

    return {
        "event_path": str(event_path),
        "rows_checked": rows_checked,
        "is_valid": first_error == "",
        "first_error": first_error,
        "first_hash": "GENESIS",
        "last_hash": last_hash,
        "event_type_count": len(event_types),
        "event_types": ",".join(sorted(event_types)),
    }


def run(event_path: Path = DEFAULT_EXPERIMENT_DIR / "eiot_event_log.csv") -> pd.DataFrame:
    result = verify_event_chain(event_path)
    output_dir = ensure_output_dir(Path(event_path).parent)
    frame = pd.DataFrame([result])
    frame.to_csv(output_dir / "event_chain_verification.csv", index=False)
    return frame


def main() -> None:
    frame = run()
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
