from __future__ import annotations

import pandas as pd

from Simulator.experiments import attack_taxonomy
from Simulator.experiments.common import ensure_output_dir


DETECTOR_FOR_CLAIMS = "adaptive-solaragent"


def capability_label(recall: float, precision: float) -> str:
    if recall >= 0.95 and precision >= 0.90:
        return "strongly_covered"
    if recall >= 0.60 and precision >= 0.85:
        return "partially_covered"
    if recall > 0.0:
        return "weakly_detected"
    return "outside_current_claim"


def claim_guidance(row: pd.Series) -> str:
    label = row["capability_level"]
    family = row["scenario_family"]
    if label == "strongly_covered":
        return "Safe to claim as covered by the current physics-grounded screening pipeline."
    if label == "partially_covered":
        return "Claim as detectable evidence for screening and audit, not complete prevention."
    if family in {"stealth_physical_boundary", "coordinated_stealth", "context_spoofing"}:
        return "State explicitly as a current limitation requiring richer temporal, neighbor, or learned context."
    return "Discuss as an open limitation of the current verifier."


def run(taxonomy: pd.DataFrame | None = None) -> pd.DataFrame:
    if taxonomy is None:
        taxonomy, _ = attack_taxonomy.run()

    selected = taxonomy[taxonomy["detector"].eq(DETECTOR_FOR_CLAIMS)].copy()
    if selected.empty:
        raise ValueError(f"Detector {DETECTOR_FOR_CLAIMS} not found in attack taxonomy results")

    selected["capability_level"] = selected.apply(
        lambda row: capability_label(float(row["recall"]), float(row["precision"])),
        axis=1,
    )
    selected["paper_claim_guidance"] = selected.apply(claim_guidance, axis=1)
    columns = [
        "attack_type",
        "scenario_family",
        "attack_rate",
        "attack_rows",
        "precision",
        "recall",
        "f1",
        "false_acceptance_rate",
        "false_rejection_rate",
        "capability_level",
        "paper_claim_guidance",
    ]
    boundary = selected[columns].sort_values(["capability_level", "attack_type"])

    output_dir = ensure_output_dir()
    boundary.to_csv(output_dir / "attack_capability_boundary.csv", index=False)
    return boundary


def main() -> None:
    boundary = run()
    print(f"attack_capability_boundary.csv: {len(boundary)} rows")
    print(boundary.to_string(index=False))


if __name__ == "__main__":
    main()
