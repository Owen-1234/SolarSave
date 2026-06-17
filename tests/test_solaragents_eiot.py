from pathlib import Path

import pandas as pd

from Simulator.agents import CoordinationLoop, EpisodeConfig
from Simulator.agents.environment import Environment
from Simulator.experiments.attack_taxonomy import run as run_attack_taxonomy
from Simulator.experiments.common import DATA_DIR, detector_adaptive, load_monthly_generation


def test_monthly_dataset_contract():
    env = Environment(DATA_DIR)
    assert len(env.dataset.nodes) == 50
    assert env.dataset.generation["city"].nunique() == 5
    assert len(env.dataset.generation) == 36_000
    assert env.dataset.generation["timestamp"].nunique() == 720
    assert int(env.dataset.generation["fdia_detected"].sum()) == 1_800


def test_coordination_loop_writes_persistent_agent_state(tmp_path: Path):
    loop = CoordinationLoop(EpisodeConfig(output_dir=tmp_path, steps=24, mode="connected_demo"))
    result = loop.run()

    state_history = pd.read_csv(result["state_history"])
    event_log = pd.read_csv(result["event_log"])
    connected_trace = pd.read_csv(result["connected_trace"])

    assert result["agents"] == 50
    assert state_history["agent_id"].nunique() == 50
    assert state_history["step"].nunique() == 24
    assert state_history["residual_history_len"].max() >= 24
    assert {"solar_report", "verification_result", "planner_decision", "market_update", "feedback_update"}.issubset(
        set(event_log["event_type"].unique())
    )
    assert not connected_trace.empty
    assert event_log["record_hash"].is_unique


def test_adaptive_detector_uses_monthly_fdia_labels():
    frame = load_monthly_generation()
    prediction = detector_adaptive(frame)
    true_positives = int((prediction & frame["fdia_detected"]).sum())
    assert len(frame) == 36_000
    assert true_positives >= 1_700


def test_attack_taxonomy_outputs_monthly_results():
    taxonomy, baseline = run_attack_taxonomy()
    assert set(taxonomy["attack_type"]).issuperset(
        {
            "dataset_fdia",
            "above_bound",
            "near_bound",
            "sensor_drift",
            "replay_attack",
            "coordinated_near_bound",
            "intermittent_burst",
        }
    )
    assert {"scenario_family", "attack_rate", "attack_rows"}.issubset(taxonomy.columns)
    assert set(baseline["detector"]).issuperset({"physics-bound", "adaptive-solaragent"})
    dataset_rows = taxonomy[taxonomy["attack_type"] == "dataset_fdia"]
    assert int(dataset_rows["records"].max()) == 36_000
    mixed_rows = taxonomy[taxonomy["attack_type"] == "near_bound"]
    assert int(mixed_rows["records"].max()) == 36_000
    assert 0 < float(mixed_rows["attack_rate"].max()) < 0.10
