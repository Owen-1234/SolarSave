from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from Simulator.agents.types import DEFAULT_DATA_DIR, DEFAULT_EXPERIMENT_DIR


DATA_DIR = DEFAULT_DATA_DIR
OUTPUT_DIR = DEFAULT_EXPERIMENT_DIR
ATTACK_SEED = 20260617
DEFAULT_ATTACK_RATE = 0.05

ATTACK_SCENARIOS = {
    "dataset_fdia": {
        "family": "original_dataset",
        "description": "Original monthly FDIA labels generated with the benchmark.",
    },
    "nighttime_impossible": {
        "family": "physics_impossible",
        "rate": 0.04,
        "description": "Night reports claim non-zero generation when the physical bound is zero.",
    },
    "above_bound": {
        "family": "physics_impossible",
        "rate": 0.05,
        "description": "Daylight reports exceed the physics-derived maximum generation bound.",
    },
    "near_bound": {
        "family": "stealth_physical_boundary",
        "rate": 0.05,
        "description": "Reports stay just below the physics rejection threshold.",
    },
    "within_bound_fraud": {
        "family": "stealth_physical_boundary",
        "rate": 0.05,
        "description": "Reports are physically plausible but economically manipulative.",
    },
    "sensor_drift": {
        "family": "temporal_persistence",
        "rate": 0.07,
        "description": "Compromised nodes accumulate a slow positive reporting drift.",
    },
    "weather_spoofing": {
        "family": "context_spoofing",
        "rate": 0.05,
        "description": "Weather context and generation reports are shifted together.",
    },
    "replay_attack": {
        "family": "temporal_persistence",
        "rate": 0.06,
        "description": "Compromised nodes replay earlier physically plausible reports.",
    },
    "neighbor_inconsistent_attack": {
        "family": "coordination_inconsistency",
        "rate": 0.05,
        "description": "A small city-local subset deviates from neighboring agents.",
    },
    "coordinated_near_bound": {
        "family": "coordinated_stealth",
        "rate": 0.06,
        "description": "Multiple nodes in the same city inflate reports near the bound.",
    },
    "intermittent_burst": {
        "family": "temporal_persistence",
        "rate": 0.04,
        "description": "Short attack bursts appear intermittently across targeted nodes.",
    },
}


def load_monthly_generation(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    frame = pd.read_csv(Path(data_dir) / "spatiotemporal_generation.csv")
    frame["fdia_detected"] = frame["fdia_detected"].astype(bool)
    if len(frame) != 36_000:
        raise ValueError(f"Expected 36,000 generation records, found {len(frame)}")
    if frame["timestamp"].nunique() != 720:
        raise ValueError(f"Expected 720 timestamps, found {frame['timestamp'].nunique()}")
    if frame["node_id"].nunique() != 50:
        raise ValueError(f"Expected 50 nodes, found {frame['node_id'].nunique()}")
    if int(frame["fdia_detected"].sum()) != 1_800:
        raise ValueError(f"Expected 1,800 FDIA records, found {int(frame['fdia_detected'].sum())}")
    return enrich(frame)


def load_market(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "market_liquidity.csv")


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["residual_W"] = data["P_reported_W"] - data["P_max_W"] * 0.978
    data["residual_ratio"] = data["residual_W"] / data["P_max_W"].clip(lower=1.0)
    data["reported_ratio"] = data["P_reported_W"] / data["P_max_W"].clip(lower=1.0)
    data["daylight"] = data["P_max_W"] > 1.0
    return data


def classify_attack_type(row: pd.Series) -> str:
    if not bool(row["fdia_detected"]):
        return "none"
    pmax = float(row["P_max_W"])
    reported = float(row["P_reported_W"])
    if pmax <= 1.0 and reported > 50:
        return "nighttime_impossible"
    ratio = reported / max(pmax, 1.0)
    if ratio > 1.05:
        return "above_bound"
    if 0.98 <= ratio <= 1.05:
        return "near_bound"
    if ratio < 0.60:
        return "within_bound_low_report"
    return "within_bound_fraud"


def attack_metadata(attack_type: str, frame: pd.DataFrame) -> dict[str, float | str]:
    scenario = ATTACK_SCENARIOS.get(attack_type, {})
    attack_rows = int(frame["ground_truth_attack"].astype(bool).sum())
    return {
        "scenario_family": str(scenario.get("family", "unknown")),
        "attack_rate": attack_rows / max(len(frame), 1),
        "attack_rows": attack_rows,
        "scenario_description": str(scenario.get("description", "")),
    }


def _rng_for(attack_type: str) -> np.random.Generator:
    offset = sum((idx + 1) * ord(ch) for idx, ch in enumerate(attack_type))
    return np.random.default_rng(ATTACK_SEED + offset)


def _reset_attack_columns(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    original_fdia = data["fdia_detected"].astype(bool)
    data["original_fdia_detected"] = original_fdia
    data.loc[original_fdia, "P_reported_W"] = (data.loc[original_fdia, "P_max_W"] * 0.978).clip(lower=0.0)
    data["fdia_detected"] = False
    data["verification_status"] = "verified"
    data["attack_type"] = "none"
    data["ground_truth_attack"] = False
    data["attack_intensity"] = 0.0
    return data


def _attack_count(total_rows: int, eligible_count: int, rate: float) -> int:
    if eligible_count <= 0:
        return 0
    return min(eligible_count, max(1, int(round(total_rows * rate))))


def _sample_indices(
    data: pd.DataFrame,
    eligible: pd.Series,
    attack_type: str,
    rate: float | None = None,
) -> pd.Index:
    rng = _rng_for(attack_type)
    eligible_index = data.index[eligible.astype(bool)]
    count = _attack_count(len(data), len(eligible_index), rate or DEFAULT_ATTACK_RATE)
    if count <= 0:
        return pd.Index([])
    return pd.Index(rng.choice(eligible_index.to_numpy(), size=count, replace=False))


def _mark_attack(data: pd.DataFrame, index: pd.Index, attack_type: str, intensity: pd.Series | float) -> None:
    if len(index) == 0:
        return
    data.loc[index, "fdia_detected"] = True
    data.loc[index, "verification_status"] = "rejected"
    data.loc[index, "attack_type"] = attack_type
    data.loc[index, "ground_truth_attack"] = True
    data.loc[index, "attack_intensity"] = intensity


def _target_nodes(data: pd.DataFrame, attack_type: str, nodes_per_city: int = 1) -> list[str]:
    rng = _rng_for(attack_type)
    nodes = []
    for _, group in data[["city", "node_id"]].drop_duplicates().groupby("city"):
        choices = sorted(group["node_id"].tolist())
        selected = rng.choice(choices, size=min(nodes_per_city, len(choices)), replace=False)
        nodes.extend(str(item) for item in selected)
    return nodes


def make_attack_frame(base: pd.DataFrame, attack_type: str) -> pd.DataFrame:
    if attack_type not in ATTACK_SCENARIOS:
        raise ValueError(f"Unknown attack type: {attack_type}")

    if attack_type == "dataset_fdia":
        data = base.copy()
        data["attack_type"] = data.apply(classify_attack_type, axis=1)
        data["ground_truth_attack"] = data["fdia_detected"]
        data["attack_intensity"] = np.where(data["ground_truth_attack"], data["reported_ratio"].sub(1.0).abs(), 0.0)
        return enrich(data)

    data = _reset_attack_columns(base)
    scenario = ATTACK_SCENARIOS[attack_type]
    rate = float(scenario.get("rate", DEFAULT_ATTACK_RATE))
    rng = _rng_for(attack_type)
    pmax = data["P_max_W"].clip(lower=1.0)
    daylight = data["P_max_W"] > 1.0

    if attack_type == "nighttime_impossible":
        index = _sample_indices(data, data["P_max_W"] <= 1.0, attack_type, rate)
        values = 350.0 + (np.arange(len(index)) % 9) * 65.0
        data.loc[index, "P_reported_W"] = values
        _mark_attack(data, index, attack_type, pd.Series(values, index=index) / pmax.loc[index])
    elif attack_type == "above_bound":
        index = _sample_indices(data, daylight, attack_type, rate)
        multiplier = pd.Series(rng.uniform(1.12, 1.75, len(index)), index=index)
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * multiplier
        _mark_attack(data, index, attack_type, multiplier - 1.0)
    elif attack_type == "near_bound":
        index = _sample_indices(data, daylight, attack_type, rate)
        multiplier = pd.Series(rng.uniform(1.005, 1.028, len(index)), index=index)
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * multiplier
        _mark_attack(data, index, attack_type, multiplier - 1.0)
    elif attack_type == "within_bound_fraud":
        index = _sample_indices(data, daylight, attack_type, rate)
        multiplier = pd.Series(rng.uniform(0.72, 0.88, len(index)), index=index)
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * multiplier
        _mark_attack(data, index, attack_type, 1.0 - multiplier)
    elif attack_type == "sensor_drift":
        targets = _target_nodes(data, attack_type, nodes_per_city=2)
        data = data.sort_values(["node_id", "timestamp"]).copy()
        elapsed = data.groupby("node_id").cumcount()
        target_mask = data["node_id"].isin(targets) & (elapsed >= 144) & daylight
        drift = ((elapsed - 144).clip(lower=0) * 0.0012).clip(upper=0.24)
        affected = data.index[target_mask]
        data.loc[affected, "P_reported_W"] = data.loc[affected, "P_reported_W"] + pmax.loc[affected] * drift.loc[affected]
        _mark_attack(data, affected, attack_type, drift.loc[affected])
    elif attack_type == "weather_spoofing":
        index = _sample_indices(data, daylight, attack_type, rate)
        context_multiplier = pd.Series(rng.uniform(1.18, 1.45, len(index)), index=index)
        report_multiplier = pd.Series(rng.uniform(0.96, 1.02, len(index)), index=index)
        data.loc[index, "irradiance_Wm2"] = data.loc[index, "irradiance_Wm2"] * context_multiplier
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * report_multiplier
        data.loc[index, "weather_spoof_factor"] = context_multiplier
        _mark_attack(data, index, attack_type, (context_multiplier - 1.0).abs())
    elif attack_type == "replay_attack":
        data = data.sort_values(["node_id", "timestamp"]).copy()
        targets = _target_nodes(data, attack_type, nodes_per_city=2)
        replayed = data.groupby("node_id")["P_reported_W"].shift(24)
        target_mask = data["node_id"].isin(targets) & replayed.notna() & daylight
        index = _sample_indices(data, target_mask, attack_type, rate)
        data.loc[index, "P_reported_W"] = replayed.loc[index]
        intensity = (data.loc[index, "P_reported_W"] - pmax.loc[index] * 0.978).abs() / pmax.loc[index]
        _mark_attack(data, index, attack_type, intensity)
    elif attack_type == "neighbor_inconsistent_attack":
        targets = _target_nodes(data, attack_type, nodes_per_city=1)
        target_mask = data["node_id"].isin(targets) & daylight
        index = _sample_indices(data, target_mask, attack_type, rate)
        multiplier = pd.Series(rng.uniform(0.34, 0.55, len(index)), index=index)
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * multiplier
        _mark_attack(data, index, attack_type, 1.0 - multiplier)
    elif attack_type == "coordinated_near_bound":
        target_city = "Shanghai"
        city_nodes = sorted(data.loc[data["city"].eq(target_city), "node_id"].unique().tolist())[:5]
        target_mask = data["node_id"].isin(city_nodes) & daylight
        index = _sample_indices(data, target_mask, attack_type, rate)
        multiplier = pd.Series(rng.uniform(1.012, 1.032, len(index)), index=index)
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * multiplier
        _mark_attack(data, index, attack_type, multiplier - 1.0)
    elif attack_type == "intermittent_burst":
        targets = _target_nodes(data, attack_type, nodes_per_city=2)
        data = data.sort_values(["node_id", "timestamp"]).copy()
        target_mask = data["node_id"].isin(targets) & daylight
        elapsed = data.groupby("node_id").cumcount()
        burst_mask = ((elapsed // 6) % 17).isin([3, 4])
        index = _sample_indices(data, target_mask & burst_mask, attack_type, rate)
        multiplier = pd.Series(rng.uniform(1.08, 1.34, len(index)), index=index)
        data.loc[index, "P_reported_W"] = data.loc[index, "P_max_W"] * multiplier
        _mark_attack(data, index, attack_type, multiplier - 1.0)

    return enrich(data)


def detector_physics_bound(frame: pd.DataFrame) -> pd.Series:
    return (frame["P_reported_W"] > frame["P_max_W"] * 1.03 + 25.0) | (
        (frame["P_max_W"] <= 1.0) & (frame["P_reported_W"] > 50.0)
    )


def detector_three_sigma(frame: pd.DataFrame) -> pd.Series:
    stats = frame.groupby(["city", "hour"])["residual_ratio"].agg(["mean", "std"]).reset_index()
    merged = frame.merge(stats, on=["city", "hour"], how="left")
    z = (merged["residual_ratio"] - merged["mean"]).abs() / merged["std"].fillna(0.0).clip(lower=0.015)
    return z > 3.0


def detector_iqr_mad(frame: pd.DataFrame) -> pd.Series:
    med = frame.groupby(["city", "hour"])["residual_ratio"].median().rename("median")
    merged = frame.join(med, on=["city", "hour"])
    mad = (merged["residual_ratio"] - merged["median"]).abs().groupby([merged["city"], merged["hour"]]).transform("median")
    score = (merged["residual_ratio"] - merged["median"]).abs() / mad.clip(lower=0.015)
    return score > 4.5


def detector_temporal(frame: pd.DataFrame) -> pd.Series:
    data = frame.sort_values(["node_id", "timestamp"]).copy()
    rolling = data.groupby("node_id")["residual_ratio"].transform(lambda series: series.shift(1).rolling(12, min_periods=4).median())
    diff = (data["residual_ratio"] - rolling.fillna(data["residual_ratio"])).abs()
    result = diff > 0.24
    return result.reindex(frame.index).fillna(False)


def detector_neighbor(frame: pd.DataFrame) -> pd.Series:
    data = frame.copy()
    median = data.groupby(["timestamp", "city"])["reported_ratio"].transform("median")
    result = ((data["reported_ratio"] - median).abs() > 0.32) & data["daylight"]
    return result


def detector_residual_memory(frame: pd.DataFrame) -> pd.Series:
    data = frame.sort_values(["node_id", "timestamp"]).copy()
    daylight_residual = data["residual_ratio"].where(data["daylight"], 0.0)
    rolling_mean = daylight_residual.groupby(data["node_id"]).transform(
        lambda series: series.shift(1).rolling(24, min_periods=8).mean()
    )
    rolling_abs = daylight_residual.abs().groupby(data["node_id"]).transform(
        lambda series: series.shift(1).rolling(24, min_periods=8).mean()
    )
    current_positive = data["residual_ratio"] > 0.030
    current_negative = data["residual_ratio"] < -0.060
    current_large = data["residual_ratio"].abs() > 0.090
    persistent_bias = (
        ((rolling_mean > 0.035) & current_positive)
        | ((rolling_mean < -0.075) & current_negative)
        | ((rolling_abs > 0.10) & current_large)
    ) & data["daylight"]
    return persistent_bias.reindex(frame.index).fillna(False)


def detector_adaptive(frame: pd.DataFrame) -> pd.Series:
    physics = detector_physics_bound(frame)
    temporal = detector_temporal(frame)
    neighbor = detector_neighbor(frame)
    memory = detector_residual_memory(frame)
    return physics | memory | (temporal & neighbor) | ((frame["residual_ratio"].abs() > 0.20) & neighbor)


DETECTORS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "3-sigma": detector_three_sigma,
    "IQR/MAD": detector_iqr_mad,
    "physics-bound": detector_physics_bound,
    "physics+temporal": lambda frame: detector_physics_bound(frame) | detector_temporal(frame),
    "physics+temporal+neighbor": lambda frame: detector_physics_bound(frame) | (detector_temporal(frame) & detector_neighbor(frame)),
    "physics+trust-memory": lambda frame: detector_physics_bound(frame) | detector_residual_memory(frame),
    "adaptive-solaragent": detector_adaptive,
}


def metrics(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float]:
    truth = y_true.astype(bool).to_numpy()
    pred = y_pred.astype(bool).to_numpy()
    tp = int((truth & pred).sum())
    tn = int((~truth & ~pred).sum())
    fp = int((~truth & pred).sum())
    fn = int((truth & ~pred).sum())
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    return {
        "records": int(len(truth)),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_acceptance_rate": fn / max(tp + fn, 1),
        "false_rejection_rate": fp / max(fp + tn, 1),
    }


def ensure_output_dir(path: Path = OUTPUT_DIR) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
