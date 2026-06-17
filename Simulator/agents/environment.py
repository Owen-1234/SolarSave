from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .types import WeatherEvent


@dataclass(frozen=True)
class MonthlyDataset:
    nodes: pd.DataFrame
    generation: pd.DataFrame
    market: pd.DataFrame
    trades: pd.DataFrame
    timestamps: list[str]


class Environment:
    """Loads and serves the required five-city, one-month EIoT benchmark data."""

    REQUIRED_GENERATION_ROWS = 36_000
    REQUIRED_FDIA_ROWS = 1_800
    REQUIRED_TIMESTAMPS = 720
    REQUIRED_NODES = 50

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.dataset = self._load()
        self.generation_by_timestamp = {
            timestamp: frame.copy()
            for timestamp, frame in self.dataset.generation.groupby("timestamp", sort=True)
        }
        self.market_by_timestamp = {
            row["timestamp"]: row for row in self.dataset.market.to_dict("records")
        }

    def _load(self) -> MonthlyDataset:
        nodes = pd.read_csv(self.data_dir / "urban_energy_nodes.csv")
        generation = pd.read_csv(self.data_dir / "spatiotemporal_generation.csv")
        market = pd.read_csv(self.data_dir / "market_liquidity.csv")
        trades = pd.read_csv(self.data_dir / "p2p_trades.csv")

        generation["fdia_detected"] = generation["fdia_detected"].astype(bool)
        generation = generation.sort_values(["timestamp", "city", "node_id"]).reset_index(drop=True)
        market = market.sort_values("timestamp").reset_index(drop=True)
        timestamps = generation["timestamp"].drop_duplicates().tolist()

        self._validate_monthly_dataset(nodes, generation, timestamps)
        return MonthlyDataset(nodes=nodes, generation=generation, market=market, trades=trades, timestamps=timestamps)

    def _validate_monthly_dataset(
        self, nodes: pd.DataFrame, generation: pd.DataFrame, timestamps: list[str]
    ) -> None:
        if len(nodes) != self.REQUIRED_NODES:
            raise ValueError(f"Expected {self.REQUIRED_NODES} nodes, found {len(nodes)}")
        if len(generation) != self.REQUIRED_GENERATION_ROWS:
            raise ValueError(
                f"Expected {self.REQUIRED_GENERATION_ROWS} generation rows, found {len(generation)}"
            )
        if len(timestamps) != self.REQUIRED_TIMESTAMPS:
            raise ValueError(f"Expected {self.REQUIRED_TIMESTAMPS} hourly timestamps, found {len(timestamps)}")
        fdia_rows = int(generation["fdia_detected"].sum())
        if fdia_rows != self.REQUIRED_FDIA_ROWS:
            raise ValueError(f"Expected {self.REQUIRED_FDIA_ROWS} FDIA rows, found {fdia_rows}")

    def timestamps(self, start_step: int, steps: int) -> list[str]:
        return self.dataset.timestamps[start_step : start_step + steps]

    def generation_step(self, timestamp: str, max_agents: int | None = None) -> pd.DataFrame:
        frame = self.generation_by_timestamp[timestamp].copy()
        if max_agents is not None:
            allowed = sorted(frame["node_id"].unique().tolist())[:max_agents]
            frame = frame[frame["node_id"].isin(allowed)].copy()
        return frame

    def weather_event(self, row: pd.Series, step: int) -> WeatherEvent:
        return WeatherEvent(
            timestamp=str(row["timestamp"]),
            step=step,
            hour=int(row["hour"]),
            city=str(row["city"]),
            irradiance_Wm2=float(row["irradiance_Wm2"]),
            air_temp_C=float(row["air_temp_C"]),
            weather_confidence=0.98 if float(row["irradiance_Wm2"]) > 0 else 0.93,
            cloud_factor=self.cloud_factor(str(row["timestamp"])),
            weather_noise=abs(float(row["P_reported_W"]) - float(row["P_max_W"])) / max(float(row["P_max_W"]), 1.0),
        )

    def cloud_factor(self, timestamp: str) -> float:
        frame = self.generation_by_timestamp[timestamp]
        daylight = frame[frame["P_max_W"] > 1.0]
        if daylight.empty:
            return 1.0
        return float((daylight["irradiance_Wm2"] / daylight["irradiance_Wm2"].max()).mean())

    def demand_W(self, timestamp: str, multiplier: float = 1.0) -> float:
        market_row = self.market_by_timestamp.get(timestamp)
        if not market_row:
            return 0.0
        verified_W = float(market_row["total_verified_MW"]) * 1_000_000.0
        daylight_floor = 35_000.0 if verified_W > 1.0 else 8_000.0
        return max(daylight_floor, verified_W * 0.72) * multiplier
