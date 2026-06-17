from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "Simulator" / "data" / "datasets_2026_04_month"
DEFAULT_EXPERIMENT_DIR = PROJECT_ROOT / "Simulator" / "data" / "experiments"


@dataclass(frozen=True)
class EpisodeConfig:
    data_dir: Path = DEFAULT_DATA_DIR
    output_dir: Path = DEFAULT_EXPERIMENT_DIR
    episode_id: str = "eiot_month_2026_04"
    start_step: int = 0
    steps: int = 720
    reward_share: float = 0.20
    reserve_buffer_W: float = 18_000.0
    demand_multiplier: float = 1.0
    planner_policy: str = "balanced"
    mode: str = "offline_benchmark"
    max_agents: int | None = None
    write_events: bool = True


@dataclass(frozen=True)
class WeatherEvent:
    timestamp: str
    step: int
    hour: int
    city: str
    irradiance_Wm2: float
    air_temp_C: float
    weather_confidence: float = 1.0
    cloud_factor: float = 1.0
    weather_noise: float = 0.0


@dataclass(frozen=True)
class Perception:
    timestamp: str
    hour: int
    city: str
    irradiance_Wm2: float
    air_temp_C: float
    p_max_W: float
    expected_report_W: float
    sensor_noise: float
    weather_confidence: float


@dataclass(frozen=True)
class SolarReport:
    timestamp: str
    step: int
    agent_id: str
    city: str
    p_max_W: float
    p_reported_W: float
    expected_report_W: float
    residual_W: float
    residual_ratio: float
    dataset_fdia: bool
    attack_type: str
    previous_trust: float
    calibration_factor: float
    participation_state: str


@dataclass(frozen=True)
class VerificationOutcome:
    status: str
    risk_level: str
    reason: str
    physics_pass: bool
    temporal_pass: bool
    neighbor_pass: bool
    neighbor_consistency_score: float
    false_acceptance_risk: float


@dataclass(frozen=True)
class PlannerDecision:
    action: str
    audit_reason: str
    human_review_required: bool
    policy: str


@dataclass(frozen=True)
class MarketSummary:
    timestamp: str
    step: int
    reward_share: float
    liquidity_share: float
    verified_supply_W: float
    reward_energy_W: float
    liquidity_energy_W: float
    factory_demand_W: float
    fulfilled_demand_W: float
    unmet_demand_W: float
    slippage_pct: float
    approved_agents: int
    rejected_agents: int
    escalated_agents: int


@dataclass(frozen=True)
class AgentFeedback:
    verification_result: str
    planner_action: str
    reward_energy_W: float
    market_slippage_pct: float
    audit_flag: bool
    unmet_demand_W: float


@dataclass
class AgentStateSnapshot:
    agent_id: str
    city: str
    trust_score: float
    calibration_factor: float
    participation_state: str
    residual_history_len: int
    last_residual_W: float
    last_market_slippage_pct: float
    last_planner_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentEvent:
    episode_id: str
    step: int
    timestamp: str
    agent_id: str
    agent_type: str
    event_type: str
    physical_state: dict[str, Any] = field(default_factory=dict)
    reported_state: dict[str, Any] = field(default_factory=dict)
    verification_result: str = ""
    planner_action: str = ""
    on_chain_action: str = ""
    tx_hash: str = ""
    market_feedback: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    record_hash: str = ""
    previous_hash: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
