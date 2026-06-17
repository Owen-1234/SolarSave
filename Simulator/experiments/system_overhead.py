from __future__ import annotations

import time

import pandas as pd

from Simulator.agents import CoordinationLoop, EpisodeConfig
from Simulator.experiments.common import ensure_output_dir


def timed(label: str, fn) -> tuple[str, float, object]:
    start = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return label, elapsed_ms, result


def run() -> pd.DataFrame:
    rows = []
    loop = CoordinationLoop(EpisodeConfig(steps=24, mode="connected_demo"))

    label, elapsed_ms, result = timed("agent_episode_24h", loop.run)
    events = max(int(result["events"]), 1)
    rows.append({"layer": "closed_loop", "metric": "episode_24h_ms", "value": elapsed_ms})
    rows.append({"layer": "event_log", "metric": "ms_per_event", "value": elapsed_ms / events})

    one_step = CoordinationLoop(EpisodeConfig(steps=1, mode="connected_demo"))
    timestamp = one_step.environment.dataset.timestamps[0]
    label, elapsed_ms, _ = timed("single_step", lambda: one_step.step(timestamp, 0))
    rows.append({"layer": "coordination", "metric": "agent_step_latency_ms", "value": elapsed_ms})
    rows.append({"layer": "solar_agent", "metric": "ms_per_report", "value": elapsed_ms / 50.0})

    for steps in [24, 168, 720]:
        label, elapsed_ms, result = timed(
            f"episode_{steps}h", lambda steps=steps: CoordinationLoop(EpisodeConfig(steps=steps, mode="offline_benchmark")).run()
        )
        rows.append({"layer": "scalability", "metric": f"episode_{steps}h_ms", "value": elapsed_ms})
        rows.append({"layer": "scalability", "metric": f"episode_{steps}h_events", "value": float(result["events"])})

    output_dir = ensure_output_dir()
    results = pd.DataFrame(rows)
    results.to_csv(output_dir / "system_overhead_results.csv", index=False)
    return results


def main() -> None:
    results = run()
    print(f"system_overhead_results.csv: {len(results)} rows")
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
