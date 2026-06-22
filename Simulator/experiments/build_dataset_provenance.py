from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from Simulator.agents.types import DEFAULT_DATA_DIR, DEFAULT_EXPERIMENT_DIR, PROJECT_ROOT
from Simulator.data import generate_monthly_datasets as generator


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
    }


def build_provenance(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    data_dir = Path(data_dir)
    generation = pd.read_csv(data_dir / "spatiotemporal_generation.csv")
    nodes = pd.read_csv(data_dir / "urban_energy_nodes.csv")
    market = pd.read_csv(data_dir / "market_liquidity.csv")
    trades = pd.read_csv(data_dir / "p2p_trades.csv")
    cache_dir = PROJECT_ROOT / "Simulator" / "data" / "cache"
    cache_files = sorted(set(cache_dir.glob("*meteo*.json")) | set(cache_dir.glob("*weather*.json")))
    ratio_summary_path = DEFAULT_EXPERIMENT_DIR / "ratio_selection_summary.csv"
    selected_ratio = None
    selected_ratio_source = None
    if ratio_summary_path.exists():
        ratio_summary = pd.read_csv(ratio_summary_path)
        selected = ratio_summary[ratio_summary["selected_ratio"].astype(bool)]
        if not selected.empty:
            selected_ratio = {
                "reward_share": float(selected.iloc[0]["reward_share"]),
                "liquidity_share": float(selected.iloc[0]["liquidity_share"]),
                "robust_score": float(selected.iloc[0]["robust_score"]),
            }
            selected_ratio_source = str(ratio_summary_path.relative_to(PROJECT_ROOT))

    return {
        "dataset_id": "SolarAgents-2026-04-month-five-city",
        "created_for": "EIoT physics-grounded embodied IoT benchmark evaluation",
        "time_window": {
            "start_inclusive": generator.DEFAULT_START_DATE,
            "end_exclusive": generator.DEFAULT_END_DATE,
            "timezone": generator.TIMEZONE,
            "hourly_timestamps": int(generation["timestamp"].nunique()),
        },
        "spatial_scope": {
            "cities": sorted(nodes["city"].unique().tolist()),
            "city_count": int(nodes["city"].nunique()),
            "nodes_per_city": int(nodes.groupby("city")["node_id"].nunique().min()),
            "node_count": int(nodes["node_id"].nunique()),
        },
        "data_sources": {
            "weather": {
                "provider": "Open-Meteo Historical Weather API",
                "variables": ["temperature_2m", "shortwave_radiation"],
                "cache_files": [_file_record(path) for path in cache_files],
            },
            "solar_modeling": {
                "library": "pvlib",
                "modeling_steps": [
                    "city-level solar position and clear-sky GHI",
                    "observed shortwave radiation capped by clear-sky envelope",
                    "node-level panel area, efficiency, and temperature coefficient",
                    "inverter derating and bounded reporting noise",
                ],
            },
        },
        "generation_method": {
            "script": str((PROJECT_ROOT / "Simulator" / "data" / "generate_monthly_datasets.py").relative_to(PROJECT_ROOT)),
            "random_seed": generator.DEFAULT_SEED,
            "nodes_per_city": generator.DEFAULT_NODES_PER_CITY,
            "default_reward_share": generator.DEFAULT_REWARD_SHARE,
            "reserve_buffer_MW": generator.DEFAULT_RESERVE_BUFFER_MW,
            "fdia_injection": {
                "attack_rate": float(generation["fdia_detected"].astype(bool).mean()),
                "attack_records": int(generation["fdia_detected"].astype(bool).sum()),
                "rules": [
                    "nighttime impossible reports use a positive reported output when P_max is near zero",
                    "daylight FDIA reports multiply P_max by one of 0.42, 1.38, 1.55, or 1.82",
                    "verification_status is initialized as rejected for injected FDIA records",
                ],
            },
        },
        "files": {
            "urban_energy_nodes": _file_record(data_dir / "urban_energy_nodes.csv") | {"rows": int(len(nodes))},
            "spatiotemporal_generation": _file_record(data_dir / "spatiotemporal_generation.csv") | {"rows": int(len(generation))},
            "market_liquidity": _file_record(data_dir / "market_liquidity.csv") | {"rows": int(len(market))},
            "p2p_trades": _file_record(data_dir / "p2p_trades.csv") | {"rows": int(len(trades))},
        },
        "selected_ratio": selected_ratio,
        "selected_ratio_source": selected_ratio_source,
        "claim_boundary": {
            "recommended_wording": "The dataset is a weather-driven, reproducible benchmark with scripted FDIA injection and market construction; it should not be described as a real utility deployment.",
            "known_limits": [
                "weather is city-level, not per-panel sensor telemetry",
                "PV nodes and FDIA labels are synthetic but physically bounded",
                "market demand and trades are simulated for benchmark control",
            ],
        },
    }


def run(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    provenance = build_provenance(data_dir)
    output_path = Path(data_dir) / "dataset_provenance.json"
    output_path.write_text(json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8")
    return provenance


def main() -> None:
    provenance = run()
    print(json.dumps(provenance, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
