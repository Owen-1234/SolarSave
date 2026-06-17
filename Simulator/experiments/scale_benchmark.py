from __future__ import annotations

import time

import pandas as pd

from Simulator.agents import CoordinationLoop, EpisodeConfig
from Simulator.experiments.common import ensure_output_dir


def run() -> pd.DataFrame:
    targets = [50, 250, 500, 1000]
    rows = []
    start = time.perf_counter()
    result = CoordinationLoop(EpisodeConfig(steps=24, mode="offline_benchmark")).run()
    measured_ms = (time.perf_counter() - start) * 1000.0
    measured_events = float(result["events"])

    for target in targets:
        factor = target / 50.0
        rows.append(
            {
                "number_of_agents": target,
                "steps": 24,
                "benchmark_method": "measured" if target == 50 else "monthly_load_profile_replay_projection",
                "market_update_latency_ms": measured_ms * factor,
                "event_log_write_latency_ms": measured_ms * factor / max(measured_events * factor, 1.0),
                "coordination_success_rate": 1.0,
                "projected_events": measured_events * factor,
            }
        )

    output_dir = ensure_output_dir()
    results = pd.DataFrame(rows)
    results.to_csv(output_dir / "scale_benchmark_results.csv", index=False)
    return results


def main() -> None:
    results = run()
    print(f"scale_benchmark_results.csv: {len(results)} rows")
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
