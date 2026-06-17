from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from Simulator.agents.types import DEFAULT_DATA_DIR, DEFAULT_EXPERIMENT_DIR


DATA_DIR = DEFAULT_DATA_DIR
OUTPUT_DIR = DEFAULT_EXPERIMENT_DIR


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


def make_attack_frame(base: pd.DataFrame, attack_type: str) -> pd.DataFrame:
    data = base.copy()
    pmax = data["P_max_W"].clip(lower=1.0)

    if attack_type == "dataset_fdia":
        data["attack_type"] = data.apply(classify_attack_type, axis=1)
        data["ground_truth_attack"] = data["fdia_detected"]
        return enrich(data)
    if attack_type == "nighttime_impossible":
        mask = data["P_max_W"] <= 1.0
        data = data[mask].copy()
        data["P_reported_W"] = 650.0 + (np.arange(len(data)) % 7) * 55.0
    elif attack_type == "above_bound":
        mask = data["P_max_W"] > 1.0
        data = data[mask].copy()
        data["P_reported_W"] = data["P_max_W"] * 1.38
    elif attack_type == "near_bound":
        mask = data["P_max_W"] > 1.0
        data = data[mask].copy()
        data["P_reported_W"] = data["P_max_W"] * 1.025
    elif attack_type == "within_bound_fraud":
        mask = data["P_max_W"] > 1.0
        data = data[mask].copy()
        data["P_reported_W"] = data["P_max_W"] * 0.82
    elif attack_type == "sensor_drift":
        data = data.sort_values(["node_id", "timestamp"]).copy()
        drift = data.groupby("node_id").cumcount() * 0.002
        data["P_reported_W"] = data["P_reported_W"] + pmax * drift.clip(upper=0.30)
    elif attack_type == "weather_spoofing":
        data["irradiance_Wm2"] = data["irradiance_Wm2"] * 1.35
        data["P_reported_W"] = data["P_reported_W"] * 1.12
    elif attack_type == "replay_attack":
        data = data.sort_values(["node_id", "timestamp"]).copy()
        data["P_reported_W"] = data.groupby("node_id")["P_reported_W"].shift(6).fillna(data["P_reported_W"])
    elif attack_type == "neighbor_inconsistent_attack":
        data = data.copy()
        target = data["node_id"].isin(["BEI-001", "SHA-001", "CHE-001", "SHE-001", "HAN-001"])
        data.loc[target & (data["P_max_W"] > 1.0), "P_reported_W"] = data.loc[
            target & (data["P_max_W"] > 1.0), "P_max_W"
        ] * 0.35
        data["fdia_detected"] = target & (data["P_max_W"] > 1.0)
        data["attack_type"] = attack_type
        data["ground_truth_attack"] = data["fdia_detected"]
        return enrich(data)
    else:
        raise ValueError(f"Unknown attack type: {attack_type}")

    data["fdia_detected"] = True
    data["attack_type"] = attack_type
    data["ground_truth_attack"] = True
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


def detector_adaptive(frame: pd.DataFrame) -> pd.Series:
    physics = detector_physics_bound(frame)
    temporal = detector_temporal(frame)
    neighbor = detector_neighbor(frame)
    return physics | (temporal & neighbor) | ((frame["residual_ratio"].abs() > 0.20) & neighbor)


DETECTORS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "3-sigma": detector_three_sigma,
    "IQR/MAD": detector_iqr_mad,
    "physics-bound": detector_physics_bound,
    "physics+temporal": lambda frame: detector_physics_bound(frame) | detector_temporal(frame),
    "physics+temporal+neighbor": lambda frame: detector_physics_bound(frame) | (detector_temporal(frame) & detector_neighbor(frame)),
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
