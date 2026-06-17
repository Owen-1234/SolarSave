from __future__ import annotations

import numpy as np
import pandas as pd

from Simulator.experiments.common import (
    detector_adaptive,
    detector_neighbor,
    detector_physics_bound,
    detector_temporal,
    ensure_output_dir,
    enrich,
    load_monthly_generation,
    metrics,
)


VARIANTS = {
    "static_physics_bound": detector_physics_bound,
    "physics_plus_residual_memory": lambda frame: detector_physics_bound(frame) | detector_temporal(frame),
    "physics_plus_residual_trust": lambda frame: detector_physics_bound(frame)
    | (detector_temporal(frame) & (frame["residual_ratio"].abs() > 0.16)),
    "physics_plus_residual_trust_neighbor": detector_adaptive,
}


def scenario_frame(base: pd.DataFrame, scenario: str) -> pd.DataFrame:
    data = base.copy()
    if scenario == "normal_weather":
        data["ground_truth_attack"] = data["fdia_detected"]
    elif scenario == "cloudy_weather":
        daylight = data["P_max_W"] > 1.0
        data.loc[daylight, "P_reported_W"] *= 0.60
        data["ground_truth_attack"] = False
    elif scenario == "sensor_drift":
        data = data.sort_values(["node_id", "timestamp"]).copy()
        drift = data.groupby("node_id").cumcount() * 0.002
        data["P_reported_W"] += data["P_max_W"].clip(lower=1.0) * drift.clip(upper=0.30)
        data["ground_truth_attack"] = drift > 0.06
    elif scenario == "high_noise":
        noise = np.sin(np.arange(len(data)) * 0.37) * data["P_max_W"].clip(lower=1.0) * 0.045
        data["P_reported_W"] = (data["P_reported_W"] + noise).clip(lower=0.0)
        data["ground_truth_attack"] = data["fdia_detected"]
    elif scenario == "cross_city_transfer":
        data = data[data["city"].isin(["Shenzhen", "Hangzhou"])].copy()
        data["ground_truth_attack"] = data["fdia_detected"]
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    return enrich(data)


def trust_convergence(prediction: pd.Series, truth: pd.Series, frame: pd.DataFrame) -> float:
    data = frame[["node_id", "timestamp"]].copy()
    data["prediction"] = prediction.astype(bool).to_numpy()
    data["truth"] = truth.astype(bool).to_numpy()
    stable_steps = []
    for _, group in data.sort_values(["node_id", "timestamp"]).groupby("node_id"):
        correctness = (group["prediction"] == group["truth"]).rolling(24, min_periods=24).mean()
        stable = correctness[correctness >= 0.90]
        stable_steps.append(float(stable.index[0] - group.index[0] + 1) if not stable.empty else float(len(group)))
    return float(np.mean(stable_steps))


def run() -> pd.DataFrame:
    base = load_monthly_generation()
    rows = []
    scenarios = ["normal_weather", "cloudy_weather", "sensor_drift", "high_noise", "cross_city_transfer"]

    for scenario in scenarios:
        frame = scenario_frame(base, scenario)
        truth = frame["ground_truth_attack"].astype(bool)
        for variant_name, detector in VARIANTS.items():
            prediction = detector(frame)
            result = metrics(truth, prediction)
            result.update(
                {
                    "scenario": scenario,
                    "variant": variant_name,
                    "calibration_error": float(frame["residual_ratio"].abs().mean()),
                    "trust_convergence_steps": trust_convergence(prediction, truth, frame),
                }
            )
            rows.append(result)

    output_dir = ensure_output_dir()
    results = pd.DataFrame(rows)
    results.to_csv(output_dir / "adaptive_agent_results.csv", index=False)
    return results


def main() -> None:
    results = run()
    print(f"adaptive_agent_results.csv: {len(results)} rows")
    print(results.sort_values(["scenario", "f1"], ascending=[True, False]).to_string(index=False))


if __name__ == "__main__":
    main()
