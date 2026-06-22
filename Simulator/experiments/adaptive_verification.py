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


def build_delta_table(results: pd.DataFrame, baseline_variant: str = "static_physics_bound") -> pd.DataFrame:
    baseline = results[results["variant"].eq(baseline_variant)].set_index("scenario")
    rows = []
    for row in results.itertuples(index=False):
        if row.variant == baseline_variant:
            continue
        base = baseline.loc[row.scenario]
        delta_recall = float(row.recall - base["recall"])
        delta_precision = float(row.precision - base["precision"])
        delta_f1 = float(row.f1 - base["f1"])
        delta_false_acceptance = float(row.false_acceptance_rate - base["false_acceptance_rate"])
        delta_false_rejection = float(row.false_rejection_rate - base["false_rejection_rate"])
        if delta_f1 > 0.01 and delta_false_rejection <= 0.02:
            interpretation = "helps_without_large_false_rejection_cost"
        elif delta_f1 > 0.01:
            interpretation = "helps_but_increases_false_rejections"
        elif delta_f1 < -0.01:
            interpretation = "hurts_or_overfits_this_scenario"
        else:
            interpretation = "no_material_change"
        rows.append(
            {
                "scenario": row.scenario,
                "baseline_variant": baseline_variant,
                "variant": row.variant,
                "delta_precision": delta_precision,
                "delta_recall": delta_recall,
                "delta_f1": delta_f1,
                "delta_false_acceptance_rate": delta_false_acceptance,
                "delta_false_rejection_rate": delta_false_rejection,
                "baseline_f1": float(base["f1"]),
                "variant_f1": float(row.f1),
                "interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows).sort_values(["scenario", "delta_f1"], ascending=[True, False])


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
    delta = build_delta_table(results)
    delta.to_csv(output_dir / "adaptive_memory_delta.csv", index=False)
    return results


def main() -> None:
    results = run()
    print(f"adaptive_agent_results.csv: {len(results)} rows")
    print("adaptive_memory_delta.csv written")
    print(results.sort_values(["scenario", "f1"], ascending=[True, False]).to_string(index=False))


if __name__ == "__main__":
    main()
