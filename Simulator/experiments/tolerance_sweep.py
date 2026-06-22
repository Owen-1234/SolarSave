from __future__ import annotations

import numpy as np
import pandas as pd

from Simulator.experiments.common import (
    ATTACK_SCENARIOS,
    ensure_output_dir,
    load_monthly_generation,
    make_attack_frame,
    metrics,
)


DEFAULT_TOLERANCES = [round(float(value), 3) for value in np.arange(1.00, 1.0801, 0.005)]
DEFAULT_ATTACK_TYPES = [
    "dataset_fdia",
    "nighttime_impossible",
    "above_bound",
    "near_bound",
    "within_bound_fraud",
    "sensor_drift",
    "weather_spoofing",
    "replay_attack",
    "neighbor_inconsistent_attack",
    "coordinated_near_bound",
    "intermittent_burst",
]


def detector_physics_bound_at_tolerance(frame: pd.DataFrame, tolerance: float) -> pd.Series:
    daylight_violation = frame["P_reported_W"] > frame["P_max_W"] * tolerance + 25.0
    night_violation = (frame["P_max_W"] <= 1.0) & (frame["P_reported_W"] > 50.0)
    return daylight_violation | night_violation


def normal_false_rejection_rate(base: pd.DataFrame, tolerance: float) -> float:
    clean = base.copy()
    clean_truth = clean["fdia_detected"].astype(bool)
    clean.loc[clean_truth, "P_reported_W"] = (clean.loc[clean_truth, "P_max_W"] * 0.978).clip(lower=0.0)
    prediction = detector_physics_bound_at_tolerance(clean, tolerance)
    return float(prediction[~clean_truth].mean())


def run(
    tolerances: list[float] | None = None,
    attack_types: list[str] | None = None,
    write_output: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = load_monthly_generation()
    tolerances = tolerances or DEFAULT_TOLERANCES
    attack_types = attack_types or DEFAULT_ATTACK_TYPES

    rows = []
    for tolerance in tolerances:
        clean_fr = normal_false_rejection_rate(base, tolerance)
        for attack_type in attack_types:
            if attack_type not in ATTACK_SCENARIOS:
                raise ValueError(f"Unknown attack type: {attack_type}")
            frame = make_attack_frame(base, attack_type)
            truth = frame["ground_truth_attack"].astype(bool)
            prediction = detector_physics_bound_at_tolerance(frame, tolerance)
            row = {
                "tolerance": tolerance,
                "attack_type": attack_type,
                "scenario_family": ATTACK_SCENARIOS[attack_type]["family"],
                "normal_false_rejection_rate": clean_fr,
                **metrics(truth, prediction),
            }
            rows.append(row)

    results = pd.DataFrame(rows)
    summary = (
        results.groupby("tolerance", as_index=False)
        .agg(
            macro_precision=("precision", "mean"),
            macro_recall=("recall", "mean"),
            macro_f1=("f1", "mean"),
            mean_false_rejection_rate=("false_rejection_rate", "mean"),
            normal_false_rejection_rate=("normal_false_rejection_rate", "first"),
            near_bound_recall=("recall", lambda series: float(results.loc[series.index, :].query("attack_type == 'near_bound'")["recall"].mean())),
            above_bound_recall=("recall", lambda series: float(results.loc[series.index, :].query("attack_type == 'above_bound'")["recall"].mean())),
            dataset_fdia_recall=("recall", lambda series: float(results.loc[series.index, :].query("attack_type == 'dataset_fdia'")["recall"].mean())),
        )
        .sort_values("tolerance")
    )
    summary["precision_recall_tradeoff"] = summary["macro_precision"] - summary["macro_recall"]

    if write_output:
        output_dir = ensure_output_dir()
        results.to_csv(output_dir / "tolerance_sweep_results.csv", index=False)
        summary.to_csv(output_dir / "tolerance_sweep_summary.csv", index=False)
    return results, summary


def main() -> None:
    results, summary = run()
    print(f"tolerance_sweep_results.csv: {len(results)} rows")
    print(f"tolerance_sweep_summary.csv: {len(summary)} rows")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
