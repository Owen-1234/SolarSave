from __future__ import annotations

import pandas as pd

from Simulator.experiments.common import DETECTORS, ensure_output_dir, load_monthly_generation, make_attack_frame, metrics


ATTACK_TYPES = [
    "dataset_fdia",
    "nighttime_impossible",
    "above_bound",
    "near_bound",
    "within_bound_fraud",
    "sensor_drift",
    "weather_spoofing",
    "replay_attack",
    "neighbor_inconsistent_attack",
]


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = load_monthly_generation()
    taxonomy_rows = []
    baseline_rows = []

    for attack_type in ATTACK_TYPES:
        frame = make_attack_frame(base, attack_type)
        truth = frame["ground_truth_attack"]
        for detector_name, detector in DETECTORS.items():
            prediction = detector(frame)
            row = {
                "attack_type": attack_type,
                "detector": detector_name,
                **metrics(truth, prediction),
            }
            taxonomy_rows.append(row)
            if attack_type == "dataset_fdia":
                baseline_rows.append(row | {"comparison_scope": "original_monthly_dataset"})

    output_dir = ensure_output_dir()
    taxonomy = pd.DataFrame(taxonomy_rows)
    baseline = pd.DataFrame(baseline_rows)
    taxonomy.to_csv(output_dir / "attack_taxonomy_results.csv", index=False)
    baseline.to_csv(output_dir / "baseline_comparison_results.csv", index=False)
    return taxonomy, baseline


def main() -> None:
    taxonomy, baseline = run()
    print(f"attack_taxonomy_results.csv: {len(taxonomy)} rows")
    print(f"baseline_comparison_results.csv: {len(baseline)} rows")
    print(taxonomy.sort_values(["attack_type", "f1"], ascending=[True, False]).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
