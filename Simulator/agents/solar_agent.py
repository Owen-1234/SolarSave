from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .types import (
    AgentFeedback,
    AgentStateSnapshot,
    Perception,
    SolarReport,
    VerificationOutcome,
    WeatherEvent,
)


@dataclass
class SolarAgent:
    agent_id: str
    city: str
    latitude: float
    longitude: float
    panel_area_m2: float
    efficiency: float
    temp_coefficient: float
    trust_score: float = 1.0
    calibration_factor: float = 1.0
    participation_state: str = "active"
    residual_history: list[float] = field(default_factory=list)
    last_market_slippage_pct: float = 0.0
    last_planner_action: str = "none"

    @classmethod
    def from_node(cls, node: pd.Series) -> "SolarAgent":
        return cls(
            agent_id=str(node["node_id"]),
            city=str(node["city"]),
            latitude=float(node["latitude"]),
            longitude=float(node["longitude"]),
            panel_area_m2=float(node["panel_area_m2"]),
            efficiency=float(node["efficiency"]),
            temp_coefficient=float(node["temp_coefficient"]),
        )

    def perceive(self, weather_event: WeatherEvent, observed_pmax_W: float) -> Perception:
        expected = max(0.0, observed_pmax_W * 0.978 * self.calibration_factor)
        return Perception(
            timestamp=weather_event.timestamp,
            hour=weather_event.hour,
            city=weather_event.city,
            irradiance_Wm2=weather_event.irradiance_Wm2,
            air_temp_C=weather_event.air_temp_C,
            p_max_W=float(observed_pmax_W),
            expected_report_W=expected,
            sensor_noise=weather_event.weather_noise,
            weather_confidence=weather_event.weather_confidence,
        )

    def report_generation(
        self,
        perception: Perception,
        step: int,
        dataset_reported_W: float,
        dataset_fdia: bool,
        attack_type: str = "dataset",
    ) -> SolarReport:
        reported = max(0.0, float(dataset_reported_W))
        residual = reported - perception.expected_report_W
        residual_ratio = residual / max(perception.p_max_W, 1.0)
        return SolarReport(
            timestamp=perception.timestamp,
            step=step,
            agent_id=self.agent_id,
            city=self.city,
            p_max_W=perception.p_max_W,
            p_reported_W=reported,
            expected_report_W=perception.expected_report_W,
            residual_W=residual,
            residual_ratio=residual_ratio,
            dataset_fdia=dataset_fdia,
            attack_type=attack_type,
            previous_trust=self.trust_score,
            calibration_factor=self.calibration_factor,
            participation_state=self.participation_state,
        )

    def verify(
        self,
        report: SolarReport,
        city_ratio_median: float,
        tolerance: float = 1.03,
        temporal_sigma: float = 0.28,
        neighbor_sigma: float = 0.35,
    ) -> VerificationOutcome:
        night_injection = report.p_max_W <= 1.0 and report.p_reported_W > 50.0
        above_bound = report.p_reported_W > report.p_max_W * tolerance + 25.0
        physics_pass = not (night_injection or above_bound)

        if len(self.residual_history) >= 4:
            recent = np.asarray(self.residual_history[-12:], dtype=float)
            scale = float(np.std(recent)) + max(25.0, report.p_max_W * 0.025)
            temporal_pass = abs(report.residual_W - float(np.mean(recent))) <= max(75.0, temporal_sigma * 4.0 * scale)
        else:
            temporal_pass = True

        own_ratio = report.p_reported_W / max(report.p_max_W, 1.0)
        neighbor_consistency_score = 1.0 - min(1.0, abs(own_ratio - city_ratio_median))
        neighbor_pass = abs(own_ratio - city_ratio_median) <= neighbor_sigma or report.p_max_W <= 1.0

        if not physics_pass:
            status = "rejected"
            risk = "high"
            reason = "physics_bound_violation"
        elif not temporal_pass and not neighbor_pass:
            status = "suspect"
            risk = "high"
            reason = "temporal_and_neighbor_inconsistency"
        elif not temporal_pass or not neighbor_pass:
            status = "suspect"
            risk = "medium"
            reason = "temporal_or_neighbor_inconsistency"
        elif abs(report.residual_ratio) > 0.18:
            status = "suspect"
            risk = "medium"
            reason = "large_within_bound_residual"
        else:
            status = "verified"
            risk = "low"
            reason = "physics_temporal_neighbor_pass"

        false_acceptance_risk = max(0.0, min(1.0, 1.0 - self.trust_score + max(0.0, report.residual_ratio)))
        return VerificationOutcome(
            status=status,
            risk_level=risk,
            reason=reason,
            physics_pass=physics_pass,
            temporal_pass=temporal_pass,
            neighbor_pass=neighbor_pass,
            neighbor_consistency_score=neighbor_consistency_score,
            false_acceptance_risk=false_acceptance_risk,
        )

    def receive_feedback(self, feedback: AgentFeedback, residual_W: float) -> None:
        previous = self.trust_score
        if feedback.planner_action == "reject":
            self.trust_score -= 0.15
        elif feedback.planner_action == "escalate":
            self.trust_score -= 0.04
        elif feedback.verification_result == "verified" and feedback.planner_action == "approve":
            self.trust_score += 0.02

        if feedback.market_slippage_pct > 1.2:
            self.trust_score -= 0.01

        self.trust_score = float(np.clip(self.trust_score, 0.0, 1.0))
        self.residual_history.append(float(residual_W))
        self.residual_history = self.residual_history[-48:]

        if len(self.residual_history) >= 6:
            recent_mean = float(np.mean(self.residual_history[-6:]))
            if recent_mean > 0:
                self.calibration_factor *= 0.995
            elif recent_mean < -100:
                self.calibration_factor *= 1.002
            self.calibration_factor = float(np.clip(self.calibration_factor, 0.85, 1.10))

        if self.trust_score < 0.18:
            self.participation_state = "suspended"
        elif self.trust_score < 0.35:
            self.participation_state = "probation"
        elif previous < 0.35 and self.trust_score >= 0.45:
            self.participation_state = "active"

        self.last_market_slippage_pct = feedback.market_slippage_pct
        self.last_planner_action = feedback.planner_action

    def snapshot(self) -> AgentStateSnapshot:
        return AgentStateSnapshot(
            agent_id=self.agent_id,
            city=self.city,
            trust_score=round(self.trust_score, 4),
            calibration_factor=round(self.calibration_factor, 4),
            participation_state=self.participation_state,
            residual_history_len=len(self.residual_history),
            last_residual_W=round(self.residual_history[-1], 4) if self.residual_history else 0.0,
            last_market_slippage_pct=round(self.last_market_slippage_pct, 4),
            last_planner_action=self.last_planner_action,
        )
