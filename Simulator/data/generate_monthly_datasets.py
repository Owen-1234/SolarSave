from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from pvlib.location import Location


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TIMEZONE = "Asia/Shanghai"
DEFAULT_START_DATE = "2026-04-01"
DEFAULT_END_DATE = "2026-05-01"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "datasets_2026_04_month"
DEFAULT_CACHE_DIR = ROOT / "data" / "cache"
DEFAULT_SEED = 20260511
DEFAULT_NODES_PER_CITY = 10
DEFAULT_REWARD_SHARE = 0.20
DEFAULT_RESERVE_BUFFER_MW = 0.018
SLIPPAGE_EPSILON_MW = 0.045


@dataclass(frozen=True)
class City:
    name: str
    latitude: float
    longitude: float


CITIES = [
    City("Beijing", 39.9042, 116.4074),
    City("Shanghai", 31.2304, 121.4737),
    City("Chengdu", 30.5728, 104.0668),
    City("Shenzhen", 22.5431, 114.0579),
    City("Hangzhou", 30.2741, 120.1551),
]


def fetch_weather_cache(start_date: str, end_date: str, cache_dir: Path) -> dict:
    """Fetch historical hourly weather for [start_date, end_date), or reuse cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"open_meteo_weather_{start_date}_{end_date}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    api_end_date = (pd.Timestamp(end_date) - pd.Timedelta(days=1)).date().isoformat()
    weather = {}
    for city in CITIES:
        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": city.latitude,
                "longitude": city.longitude,
                "start_date": start_date,
                "end_date": api_end_date,
                "hourly": "temperature_2m,shortwave_radiation",
                "timezone": TIMEZONE,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        hourly = payload["hourly"]
        weather[city.name] = {
            "source": "Open-Meteo Historical Weather API",
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "timezone": payload.get("timezone"),
            "time": hourly["time"],
            "temperature_2m_C": hourly["temperature_2m"],
            "shortwave_radiation_Wm2": hourly["shortwave_radiation"],
        }

    cache_path.write_text(json.dumps(weather, indent=2), encoding="utf-8")
    return weather


def make_nodes(rng: np.random.Generator, nodes_per_city: int) -> pd.DataFrame:
    rows = []
    install_start = pd.Timestamp("2020-01-01")
    install_days = (pd.Timestamp("2024-05-31") - install_start).days

    for city in CITIES:
        for idx in range(nodes_per_city):
            rows.append(
                {
                    "node_id": f"{city.name[:3].upper()}-{idx + 1:03d}",
                    "city": city.name,
                    "latitude": round(city.latitude + rng.normal(0, 0.035), 6),
                    "longitude": round(city.longitude + rng.normal(0, 0.035), 6),
                    "panel_area_m2": round(float(rng.uniform(18.0, 64.0)), 2),
                    "efficiency": round(float(rng.uniform(0.176, 0.226)), 4),
                    "temp_coefficient": round(float(rng.uniform(-0.0046, -0.0032)), 5),
                    "install_date": (
                        install_start + pd.Timedelta(days=int(rng.integers(0, install_days)))
                    ).date().isoformat(),
                }
            )

    return pd.DataFrame(rows)


def city_weather_frame(city: City, weather_cache: dict, start_date: str, end_date: str) -> pd.DataFrame:
    observed = weather_cache[city.name]
    times = pd.DatetimeIndex(pd.to_datetime(observed["time"]))
    if times.tz is None:
        times = times.tz_localize(TIMEZONE)
    else:
        times = times.tz_convert(TIMEZONE)

    end_timestamp = pd.Timestamp(end_date, tz=TIMEZONE)
    times_mask = times < end_timestamp
    times = times[times_mask]

    site = Location(city.latitude, city.longitude, tz=TIMEZONE)
    clearsky = site.get_clearsky(times, model="ineichen")
    solar_position = site.get_solarposition(times)

    frame = pd.DataFrame(
        {
            "timestamp": times,
            "hour": times.hour,
            "city": city.name,
            "observed_shortwave_Wm2": np.asarray(observed["shortwave_radiation_Wm2"])[times_mask],
            "air_temp_C": np.asarray(observed["temperature_2m_C"])[times_mask],
            "clearsky_ghi_Wm2": clearsky["ghi"].to_numpy(),
            "solar_zenith": solar_position["zenith"].to_numpy(),
        }
    )

    daylight = frame["solar_zenith"] < 90
    capped_observed = np.minimum(
        frame["observed_shortwave_Wm2"].clip(lower=0),
        frame["clearsky_ghi_Wm2"].clip(lower=0) * 1.08,
    )
    frame["irradiance_Wm2"] = np.where(daylight, capped_observed, 0.0)
    return frame


def make_generation(
    nodes: pd.DataFrame,
    weather_cache: dict,
    rng: np.random.Generator,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    weather_by_city = {city.name: city_weather_frame(city, weather_cache, start_date, end_date) for city in CITIES}
    rows = []

    for node in nodes.to_dict("records"):
        city_weather = weather_by_city[node["city"]]
        for _, hour in city_weather.iterrows():
            irradiance = float(hour["irradiance_Wm2"])
            temp_loss = 1.0 + float(node["temp_coefficient"]) * (float(hour["air_temp_C"]) - 25.0)
            temp_loss = float(np.clip(temp_loss, 0.78, 1.08))
            inverter_derate = float(rng.uniform(0.965, 0.992))
            p_max = max(0.0, irradiance * node["panel_area_m2"] * node["efficiency"] * temp_loss)
            reported = p_max * inverter_derate * float(rng.normal(1.0, 0.012))

            rows.append(
                {
                    "timestamp": hour["timestamp"].isoformat(),
                    "hour": int(hour["hour"]),
                    "node_id": node["node_id"],
                    "city": node["city"],
                    "latitude": node["latitude"],
                    "longitude": node["longitude"],
                    "irradiance_Wm2": round(irradiance, 2),
                    "air_temp_C": round(float(hour["air_temp_C"]), 2),
                    "P_max_W": round(p_max, 2),
                    "P_reported_W": round(max(0.0, reported), 2),
                    "fdia_detected": False,
                    "verification_status": "verified",
                }
            )

    generation = pd.DataFrame(rows)
    attack_count = int(round(len(generation) * 0.05))
    attack_indices = rng.choice(generation.index.to_numpy(), size=attack_count, replace=False)

    for index in attack_indices:
        p_max = generation.at[index, "P_max_W"]
        if p_max <= 1:
            generation.at[index, "P_reported_W"] = round(float(rng.uniform(350.0, 1200.0)), 2)
        else:
            generation.at[index, "P_reported_W"] = round(
                p_max * float(rng.choice([0.42, 1.38, 1.55, 1.82])), 2
            )
        generation.at[index, "fdia_detected"] = True
        generation.at[index, "verification_status"] = "rejected"

    return generation


def make_market_liquidity(
    generation: pd.DataFrame,
    reward_share: float = DEFAULT_REWARD_SHARE,
    reserve_buffer_MW: float = DEFAULT_RESERVE_BUFFER_MW,
) -> pd.DataFrame:
    verified = generation[generation["verification_status"] == "verified"].copy()
    verified["verified_MW"] = verified["P_reported_W"] / 1_000_000

    hourly = (
        verified.groupby(["timestamp", "hour"], as_index=False)["verified_MW"]
        .sum()
        .rename(columns={"verified_MW": "total_verified_MW"})
        .sort_values("timestamp")
    )
    liquidity_share = 1.0 - reward_share
    daylight = hourly["total_verified_MW"] > 0.002
    hourly["reward_share"] = reward_share
    hourly["liquidity_share"] = liquidity_share
    hourly["producer_reward_MW"] = hourly["total_verified_MW"] * reward_share
    hourly["solarchain_liquidity_MW"] = hourly["total_verified_MW"] * liquidity_share + reserve_buffer_MW
    hourly["demand_MW"] = np.where(daylight, np.maximum(0.008, hourly["total_verified_MW"] * 0.72), 0.008)
    hourly["fulfilled_demand_MW"] = np.minimum(hourly["demand_MW"], hourly["solarchain_liquidity_MW"])
    hourly["unmet_demand_MW"] = np.maximum(0.0, hourly["demand_MW"] - hourly["fulfilled_demand_MW"])
    hourly["slippage_solarchain_pct"] = 100.0 * hourly["fulfilled_demand_MW"] / (
        hourly["solarchain_liquidity_MW"] + SLIPPAGE_EPSILON_MW
    )

    baseline_reward_share = 0.50
    baseline_liquidity_share = 1.0 - baseline_reward_share
    hourly["baseline_liquidity_MW"] = hourly["total_verified_MW"] * baseline_liquidity_share + 0.008
    hourly["slippage_baseline_pct"] = 100.0 * hourly["fulfilled_demand_MW"] / (
        hourly["baseline_liquidity_MW"] + 0.028
    )

    columns = [
        "timestamp",
        "hour",
        "total_verified_MW",
        "reward_share",
        "liquidity_share",
        "producer_reward_MW",
        "solarchain_liquidity_MW",
        "demand_MW",
        "fulfilled_demand_MW",
        "unmet_demand_MW",
        "baseline_liquidity_MW",
        "slippage_solarchain_pct",
        "slippage_baseline_pct",
    ]
    return hourly[columns].round(
        {
            "total_verified_MW": 6,
            "reward_share": 3,
            "liquidity_share": 3,
            "producer_reward_MW": 6,
            "solarchain_liquidity_MW": 6,
            "demand_MW": 6,
            "fulfilled_demand_MW": 6,
            "unmet_demand_MW": 6,
            "baseline_liquidity_MW": 6,
            "slippage_solarchain_pct": 4,
            "slippage_baseline_pct": 4,
        }
    )


def make_trades(market: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    factories = [
        ("FAC-BJ-01", "Beijing"),
        ("FAC-SH-01", "Shanghai"),
        ("FAC-CD-01", "Chengdu"),
        ("FAC-SZ-01", "Shenzhen"),
        ("FAC-HZ-01", "Hangzhou"),
        ("FAC-SH-02", "Shanghai"),
    ]
    daylight = market[market["total_verified_MW"] > 0.002].sort_values("timestamp").reset_index(drop=True)
    rows = []

    for hour_index, hour_row in daylight.iterrows():
        for trade_slot in range(3):
            factory_id, city = factories[(hour_index + trade_slot) % len(factories)]
            purchase = min(
                float(hour_row["solarchain_liquidity_MW"]) * float(rng.uniform(0.055, 0.16)),
                float(hour_row["total_verified_MW"]) * float(rng.uniform(0.08, 0.22)),
            )
            if purchase <= 0:
                continue
            rows.append(
                {
                    "trade_id": f"TRD-{len(rows) + 1:05d}",
                    "timestamp": hour_row["timestamp"],
                    "hour": int(hour_row["hour"]),
                    "factory_id": factory_id,
                    "city": city,
                    "energy_purchased_MW": round(purchase, 6),
                    "tokens_burned": round(purchase * 1000 * float(rng.uniform(0.93, 1.08)), 4),
                    "exergy_dissipated_MJ": round(purchase * 3600 * float(rng.uniform(0.015, 0.038)), 4),
                }
            )

    columns = [
        "trade_id",
        "timestamp",
        "hour",
        "factory_id",
        "city",
        "energy_purchased_MW",
        "tokens_burned",
        "exergy_dissipated_MJ",
    ]
    return pd.DataFrame(rows, columns=columns)


def write_datasets(
    start_date: str,
    end_date: str,
    output_dir: Path,
    cache_dir: Path,
    seed: int,
    nodes_per_city: int,
    reward_share: float,
    reserve_buffer_MW: float,
) -> None:
    rng = np.random.default_rng(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    weather_cache = fetch_weather_cache(start_date, end_date, cache_dir)
    nodes = make_nodes(rng, nodes_per_city)
    generation = make_generation(nodes, weather_cache, rng, start_date, end_date)
    market = make_market_liquidity(
        generation,
        reward_share=reward_share,
        reserve_buffer_MW=reserve_buffer_MW,
    )
    trades = make_trades(market, rng)

    nodes.to_csv(output_dir / "urban_energy_nodes.csv", index=False)
    generation.to_csv(output_dir / "spatiotemporal_generation.csv", index=False)
    market.to_csv(output_dir / "market_liquidity.csv", index=False)
    trades.to_csv(output_dir / "p2p_trades.csv", index=False)

    unique_cities = sorted(generation["city"].unique().tolist())
    unique_hours = generation["timestamp"].nunique()
    print(f"cities: {', '.join(unique_cities)}")
    print(f"urban_energy_nodes.csv: {len(nodes)} rows")
    print(f"spatiotemporal_generation.csv: {len(generation)} rows")
    print(f"unique timestamps: {unique_hours}")
    print(f"FDIA rows: {int(generation['fdia_detected'].sum())}")
    print(f"reward/liquidity split: {reward_share:.3f}/{1.0 - reward_share:.3f}")
    print(f"market_liquidity.csv: {len(market)} rows")
    print(f"p2p_trades.csv: {len(trades)} rows")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate five-city monthly SolarChain-Eval datasets")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--nodes-per-city", type=int, default=DEFAULT_NODES_PER_CITY)
    parser.add_argument("--reward-share", type=float, default=DEFAULT_REWARD_SHARE)
    parser.add_argument("--reserve-buffer-MW", type=float, default=DEFAULT_RESERVE_BUFFER_MW)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_datasets(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        seed=args.seed,
        nodes_per_city=args.nodes_per_city,
        reward_share=args.reward_share,
        reserve_buffer_MW=args.reserve_buffer_MW,
    )


if __name__ == "__main__":
    main()
