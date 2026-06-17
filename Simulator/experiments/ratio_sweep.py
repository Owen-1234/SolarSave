from __future__ import annotations

import numpy as np
import pandas as pd

from Simulator.experiments.common import ensure_output_dir, load_market, load_monthly_generation


REWARD_SHARES = [round(float(value), 3) for value in np.arange(0.0, 1.0001, 0.025)]
MIN_AVG_FULFILLED_RATIO = 0.90
MIN_WORST_CASE_FULFILLED_RATIO = 0.80
MAX_AVG_SLIPPAGE_PCT = 40.0
MIN_AVG_PRODUCER_REWARD_KWH = 5_000.0
SCENARIOS = {
    "low_demand": {"demand_multiplier": 0.5, "generation_multiplier": 1.0, "fdia_loss": 0.0, "volatility": 0.0},
    "normal_demand": {"demand_multiplier": 1.0, "generation_multiplier": 1.0, "fdia_loss": 0.0, "volatility": 0.0},
    "high_demand": {"demand_multiplier": 1.5, "generation_multiplier": 1.0, "fdia_loss": 0.0, "volatility": 0.0},
    "cloudy_weather": {"demand_multiplier": 1.0, "generation_multiplier": 0.6, "fdia_loss": 0.0, "volatility": 0.0},
    "high_fdia_10": {"demand_multiplier": 1.0, "generation_multiplier": 1.0, "fdia_loss": 0.10, "volatility": 0.0},
    "high_fdia_20": {"demand_multiplier": 1.0, "generation_multiplier": 1.0, "fdia_loss": 0.20, "volatility": 0.0},
    "high_volatility": {"demand_multiplier": 1.0, "generation_multiplier": 1.0, "fdia_loss": 0.0, "volatility": 0.25},
}


def gini(values: pd.Series) -> float:
    arr = np.sort(values.to_numpy(dtype=float))
    if arr.size == 0 or arr.sum() <= 0:
        return 0.0
    index = np.arange(1, arr.size + 1)
    return float((2 * index @ arr) / (arr.size * arr.sum()) - (arr.size + 1) / arr.size)


def pareto_flags(frame: pd.DataFrame) -> pd.Series:
    flags = []
    for _, row in frame.iterrows():
        dominated = frame[
            (frame["fulfilled_demand_ratio"] >= row["fulfilled_demand_ratio"])
            & (frame["producer_reward_kWh"] >= row["producer_reward_kWh"])
            & (frame["avg_slippage_pct"] <= row["avg_slippage_pct"])
            & (
                (frame["fulfilled_demand_ratio"] > row["fulfilled_demand_ratio"])
                | (frame["producer_reward_kWh"] > row["producer_reward_kWh"])
                | (frame["avg_slippage_pct"] < row["avg_slippage_pct"])
            )
        ]
        flags.append(dominated.empty)
    return pd.Series(flags, index=frame.index)


def normalize_positive(series: pd.Series) -> pd.Series:
    minimum = float(series.min())
    maximum = float(series.max())
    if maximum <= minimum:
        return pd.Series(1.0, index=series.index)
    return (series - minimum) / (maximum - minimum)


def normalize_negative(series: pd.Series) -> pd.Series:
    minimum = float(series.min())
    maximum = float(series.max())
    if maximum <= minimum:
        return pd.Series(1.0, index=series.index)
    return (maximum - series) / (maximum - minimum)


def add_selection_scores(results: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored = []
    for _, scenario_frame in results.groupby("scenario"):
        frame = scenario_frame.copy()
        frame["reward_score"] = normalize_positive(frame["producer_reward_kWh"])
        frame["slippage_score"] = normalize_negative(frame["avg_slippage_pct"])
        frame["unmet_score"] = normalize_negative(frame["unmet_demand_MWh"])
        frame["drawdown_score"] = normalize_negative(frame["liquidity_drawdown_pct"])
        frame["scenario_score"] = (
            0.50 * frame["fulfilled_demand_ratio"]
            + 0.20 * frame["reward_score"]
            + 0.15 * frame["slippage_score"]
            + 0.10 * frame["unmet_score"]
            + 0.05 * frame["drawdown_score"]
        )
        scored.append(frame)

    results = pd.concat(scored, ignore_index=True)
    summary = (
        results.groupby("reward_share", as_index=False)
        .agg(
            liquidity_share=("liquidity_share", "first"),
            avg_scenario_score=("scenario_score", "mean"),
            worst_scenario_score=("scenario_score", "min"),
            avg_fulfilled_demand_ratio=("fulfilled_demand_ratio", "mean"),
            worst_fulfilled_demand_ratio=("fulfilled_demand_ratio", "min"),
            avg_producer_reward_kWh=("producer_reward_kWh", "mean"),
            avg_slippage_pct=("avg_slippage_pct", "mean"),
            max_slippage_pct=("peak_slippage_pct", "max"),
            avg_unmet_demand_MWh=("unmet_demand_MWh", "mean"),
            pareto_scenarios=("pareto_efficient", "sum"),
        )
    )
    summary["robust_score"] = (
        0.75 * summary["avg_scenario_score"] + 0.25 * summary["worst_scenario_score"]
    )
    summary["feasible"] = (
        (summary["avg_fulfilled_demand_ratio"] >= MIN_AVG_FULFILLED_RATIO)
        & (summary["worst_fulfilled_demand_ratio"] >= MIN_WORST_CASE_FULFILLED_RATIO)
        & (summary["avg_slippage_pct"] <= MAX_AVG_SLIPPAGE_PCT)
        & (summary["avg_producer_reward_kWh"] >= MIN_AVG_PRODUCER_REWARD_KWH)
    )

    feasible = summary[summary["feasible"]].copy()
    if feasible.empty:
        selected_reward_share = float(summary.sort_values("robust_score", ascending=False).iloc[0]["reward_share"])
    else:
        selected_reward_share = float(feasible.sort_values("robust_score", ascending=False).iloc[0]["reward_share"])

    summary["selected_ratio"] = summary["reward_share"].eq(selected_reward_share)
    results["selected_ratio"] = results["reward_share"].eq(selected_reward_share)
    return results, summary


def run() -> pd.DataFrame:
    generation = load_monthly_generation()
    market = load_market()
    verified = generation[~generation["fdia_detected"]].copy()
    hourly_supply = (
        verified.groupby("timestamp", as_index=False)["P_reported_W"].sum().rename(columns={"P_reported_W": "verified_supply_W"})
    )
    hourly = market[["timestamp", "hour"]].merge(hourly_supply, on="timestamp", how="left").fillna({"verified_supply_W": 0.0})
    daylight = hourly["verified_supply_W"] > 2_000.0

    rows = []
    for scenario, params in SCENARIOS.items():
        volatility_curve = 1.0 + params["volatility"] * np.sin(np.arange(len(hourly)) * 0.31)
        supply_W = hourly["verified_supply_W"] * params["generation_multiplier"] * (1.0 - params["fdia_loss"])
        demand_W = np.maximum(8_000.0, hourly["verified_supply_W"] * 0.72) * params["demand_multiplier"] * volatility_curve

        for reward_share in REWARD_SHARES:
            exit_penalty = 1.0
            if reward_share < 0.10:
                exit_penalty = 0.82
            elif reward_share < 0.20:
                exit_penalty = 0.93
            adjusted_supply_W = supply_W * exit_penalty
            liquidity_share = 1.0 - reward_share
            reward_W = adjusted_supply_W * reward_share
            liquidity_W = adjusted_supply_W * liquidity_share + 18_000.0
            fulfilled_W = np.minimum(demand_W, liquidity_W)
            unmet_W = np.maximum(0.0, demand_W - fulfilled_W)
            slippage_pct = 100.0 * fulfilled_W / (liquidity_W + 45_000.0)
            drawdown = 100.0 * (liquidity_W.max() - liquidity_W.min()) / max(float(liquidity_W.max()), 1.0)
            fulfilled_ratio = float(fulfilled_W.sum() / max(float(demand_W.sum()), 1.0))
            reward_kWh = float(reward_W.sum() / 1000.0)
            composite = (
                fulfilled_ratio * 0.45
                + min(reward_kWh / 250.0, 1.0) * 0.25
                + (1.0 - min(float(slippage_pct.mean()) / 100.0, 1.0)) * 0.20
                + (1.0 - min(drawdown / 100.0, 1.0)) * 0.10
            )
            rows.append(
                {
                    "scenario": scenario,
                    "reward_share": reward_share,
                    "liquidity_share": liquidity_share,
                    "avg_liquidity_MW": float(liquidity_W.mean() / 1_000_000.0),
                    "min_daylight_liquidity_MW": float(liquidity_W[daylight].min() / 1_000_000.0),
                    "avg_slippage_pct": float(slippage_pct.mean()),
                    "peak_slippage_pct": float(slippage_pct.max()),
                    "producer_reward_kWh": reward_kWh,
                    "reward_gini": gini(reward_W),
                    "fulfilled_demand_ratio": fulfilled_ratio,
                    "unmet_demand_MWh": float(unmet_W.sum() / 1_000_000.0),
                    "liquidity_drawdown_pct": drawdown,
                    "composite_score": composite,
                }
            )

    results = pd.DataFrame(rows)
    results["pareto_efficient"] = results.groupby("scenario", group_keys=False).apply(pareto_flags)
    results, selection = add_selection_scores(results)
    output_dir = ensure_output_dir()
    results.to_csv(output_dir / "ratio_sweep_results.csv", index=False)
    selection.to_csv(output_dir / "ratio_selection_summary.csv", index=False)
    return results


def main() -> None:
    results = run()
    print(f"ratio_sweep_results.csv: {len(results)} rows")
    selected = results[results["selected_ratio"]]
    print(selected.to_string(index=False))


if __name__ == "__main__":
    main()
