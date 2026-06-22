from pathlib import Path

import pandas as pd

from Simulator.agents import CoordinationLoop, EpisodeConfig
from Simulator.experiments import adaptive_verification, build_dataset_provenance, tolerance_sweep
from Simulator.experiments.attack_capability_boundary import run as run_attack_capability_boundary
from Simulator.experiments.attack_taxonomy import run as run_attack_taxonomy
from Simulator.experiments.verify_event_chain import run as run_event_chain_verification


def test_tolerance_sweep_reports_near_bound_tradeoff():
    results, summary = tolerance_sweep.run(
        tolerances=[1.0, 1.03, 1.08],
        attack_types=["above_bound", "near_bound", "within_bound_fraud"],
        write_output=False,
    )

    assert {"tolerance", "attack_type", "normal_false_rejection_rate", "recall"}.issubset(results.columns)
    assert set(results["attack_type"]) == {"above_bound", "near_bound", "within_bound_fraud"}
    assert summary["tolerance"].tolist() == [1.0, 1.03, 1.08]
    assert summary.loc[summary["tolerance"].eq(1.0), "near_bound_recall"].iloc[0] >= summary.loc[
        summary["tolerance"].eq(1.08), "near_bound_recall"
    ].iloc[0]
    assert summary["normal_false_rejection_rate"].between(0.0, 1.0).all()


def test_adaptive_verification_writes_delta_table():
    results = adaptive_verification.run()
    delta = adaptive_verification.build_delta_table(results)

    assert not delta.empty
    assert {"delta_f1", "delta_recall", "interpretation"}.issubset(delta.columns)
    assert "physics_plus_residual_memory" in set(delta["variant"])


def test_attack_capability_boundary_marks_stealth_limits():
    taxonomy, _ = run_attack_taxonomy()
    boundary = run_attack_capability_boundary(taxonomy)

    near_bound = boundary[boundary["attack_type"].eq("near_bound")].iloc[0]
    assert near_bound["capability_level"] == "outside_current_claim"
    assert "limitation" in near_bound["paper_claim_guidance"]


def test_event_chain_verification_on_short_episode(tmp_path: Path):
    loop = CoordinationLoop(EpisodeConfig(output_dir=tmp_path, steps=3, mode="connected_demo"))
    result = loop.run()
    verification = run_event_chain_verification(Path(result["event_log"]))

    row = verification.iloc[0]
    assert bool(row["is_valid"])
    assert int(row["rows_checked"]) == int(result["events"])
    assert "solar_report" in row["event_types"]


def test_dataset_provenance_contains_claim_boundaries():
    provenance = build_dataset_provenance.build_provenance()

    assert provenance["spatial_scope"]["node_count"] == 50
    assert provenance["time_window"]["hourly_timestamps"] == 720
    assert provenance["generation_method"]["fdia_injection"]["attack_records"] == 1800
    assert "known_limits" in provenance["claim_boundary"]
