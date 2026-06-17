from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .environment import Environment
from .event_bus import EventBus
from .market_agent import MarketAgent, build_factory_agents
from .planner_agent import PlannerAgent
from .solar_agent import SolarAgent
from .types import AgentEvent, AgentFeedback, EpisodeConfig, MarketSummary, SolarReport, VerificationOutcome


class CoordinationLoop:
    """Closed-loop SolarAgents simulator over the required five-city monthly data."""

    def __init__(self, config: EpisodeConfig | None = None) -> None:
        self.config = config or EpisodeConfig()
        self.environment = Environment(Path(self.config.data_dir))
        self.agents = {
            str(row["node_id"]): SolarAgent.from_node(row)
            for _, row in self.environment.dataset.nodes.iterrows()
        }
        if self.config.max_agents is not None:
            keep = sorted(self.agents)[: self.config.max_agents]
            self.agents = {agent_id: self.agents[agent_id] for agent_id in keep}
        self.planner = PlannerAgent(policy=self.config.planner_policy)
        self.market = MarketAgent(reward_share=self.config.reward_share, reserve_buffer_W=self.config.reserve_buffer_W)
        self.factories = build_factory_agents()
        self.event_bus = EventBus(Path(self.config.output_dir))
        self.last_market_summary: MarketSummary | None = None
        self.last_decisions: list[dict[str, Any]] = []

    def run(self) -> dict[str, Any]:
        market_rows: list[dict[str, Any]] = []
        decision_rows: list[dict[str, Any]] = []
        state_rows: list[dict[str, Any]] = []

        for relative_step, timestamp in enumerate(
            self.environment.timestamps(self.config.start_step, self.config.steps)
        ):
            step = self.config.start_step + relative_step
            step_result = self.step(timestamp, step)
            market_rows.append(asdict(step_result["market_summary"]))
            decision_rows.extend(step_result["decisions"])
            state_rows.extend(agent.snapshot().to_dict() | {"step": step, "timestamp": timestamp} for agent in self.agents.values())

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(market_rows).to_csv(output_dir / "agent_market_summary.csv", index=False)
        pd.DataFrame(decision_rows).to_csv(output_dir / "agent_decisions.csv", index=False)
        pd.DataFrame(state_rows).to_csv(output_dir / "agent_state_history.csv", index=False)

        return {
            "episode_id": self.config.episode_id,
            "steps": len(market_rows),
            "agents": len(self.agents),
            "events": len(self.event_bus.events),
            "event_log": str(self.event_bus.event_path),
            "audit_log": str(self.event_bus.audit_path),
            "connected_trace": str(self.event_bus.connected_path),
            "market_summary": str(output_dir / "agent_market_summary.csv"),
            "decisions": str(output_dir / "agent_decisions.csv"),
            "state_history": str(output_dir / "agent_state_history.csv"),
        }

    def step(self, timestamp: str, step: int) -> dict[str, Any]:
        step_start = time.perf_counter()
        frame = self.environment.generation_step(timestamp, self.config.max_agents)
        reports: list[SolarReport] = []
        outcomes: dict[str, VerificationOutcome] = {}
        decisions: list[dict[str, Any]] = []

        report_start = time.perf_counter()
        for _, row in frame.iterrows():
            agent = self.agents[str(row["node_id"])]
            weather = self.environment.weather_event(row, step)
            perception = agent.perceive(weather, float(row["P_max_W"]))
            report = agent.report_generation(
                perception=perception,
                step=step,
                dataset_reported_W=float(row["P_reported_W"]),
                dataset_fdia=bool(row["fdia_detected"]),
                attack_type=self._attack_type(row),
            )
            reports.append(report)
            self._emit_report_event(agent, report, perception, (time.perf_counter() - report_start) * 1000.0)

        city_medians = self._city_ratio_medians(reports)
        approved_supply_W = 0.0
        approved_reports: list[SolarReport] = []
        rejected = 0
        escalated = 0

        for report in reports:
            agent = self.agents[report.agent_id]
            verify_start = time.perf_counter()
            outcome = agent.verify(report, city_medians.get(report.city, 1.0))
            outcomes[report.agent_id] = outcome
            self._emit_verification_event(report, outcome, (time.perf_counter() - verify_start) * 1000.0)

            decision_start = time.perf_counter()
            decision = self.planner.decide(report, outcome, agent.trust_score)
            latency = (time.perf_counter() - decision_start) * 1000.0

            if decision.action == "approve":
                approved_supply_W += min(report.p_reported_W, report.p_max_W)
                approved_reports.append(report)
            elif decision.action == "reject":
                rejected += 1
            elif decision.action == "escalate":
                escalated += 1

            decision_row = {
                "episode_id": self.config.episode_id,
                "step": step,
                "timestamp": report.timestamp,
                "agent_id": report.agent_id,
                "city": report.city,
                "p_max_W": report.p_max_W,
                "p_reported_W": report.p_reported_W,
                "dataset_fdia": report.dataset_fdia,
                "attack_type": report.attack_type,
                "verification_result": outcome.status,
                "verification_reason": outcome.reason,
                "planner_action": decision.action,
                "audit_reason": decision.audit_reason,
                "trust_before": report.previous_trust,
                "human_review_required": decision.human_review_required,
            }
            decisions.append(decision_row)
            self._emit_planner_event(report, outcome, decision_row, latency)

        factory_demand_W = self.environment.demand_W(timestamp, self.config.demand_multiplier)
        market_start = time.perf_counter()
        market_summary = self.market.settle(
            timestamp=timestamp,
            step=step,
            approved_supply_W=approved_supply_W,
            factory_demand_W=factory_demand_W,
            approved_agents=len(approved_reports),
            rejected_agents=rejected,
            escalated_agents=escalated,
        )
        self.last_market_summary = market_summary
        self.last_decisions = decisions
        self._emit_market_event(market_summary, (time.perf_counter() - market_start) * 1000.0)

        reward_per_W = market_summary.reward_energy_W / max(1.0, approved_supply_W)
        for report in reports:
            agent = self.agents[report.agent_id]
            outcome = outcomes[report.agent_id]
            decision_action = next(item["planner_action"] for item in decisions if item["agent_id"] == report.agent_id)
            reward_W = min(report.p_reported_W, report.p_max_W) * reward_per_W if decision_action == "approve" else 0.0
            previous_trust = agent.trust_score
            feedback = AgentFeedback(
                verification_result=outcome.status,
                planner_action=decision_action,
                reward_energy_W=reward_W,
                market_slippage_pct=market_summary.slippage_pct,
                audit_flag=decision_action != "approve" or outcome.status != "verified",
                unmet_demand_W=market_summary.unmet_demand_W,
            )
            agent.receive_feedback(feedback, report.residual_W)
            self._emit_feedback_event(report, previous_trust, agent.trust_score, feedback)

        for factory in self.factories:
            factory.receive_feedback(market_summary.unmet_demand_W / len(self.factories))

        return {
            "market_summary": market_summary,
            "decisions": decisions,
            "latency_ms": (time.perf_counter() - step_start) * 1000.0,
        }

    def _attack_type(self, row: pd.Series) -> str:
        pmax = float(row["P_max_W"])
        reported = float(row["P_reported_W"])
        fdia = bool(row["fdia_detected"])
        if not fdia:
            return "none"
        if pmax <= 1.0 and reported > 50.0:
            return "nighttime_impossible"
        ratio = reported / max(pmax, 1.0)
        if ratio > 1.05:
            return "above_bound"
        if 0.98 <= ratio <= 1.05:
            return "near_bound"
        if ratio < 0.60:
            return "within_bound_low_report"
        return "within_bound_fraud"

    def _city_ratio_medians(self, reports: list[SolarReport]) -> dict[str, float]:
        rows = [
            {"city": report.city, "ratio": report.p_reported_W / max(report.p_max_W, 1.0)}
            for report in reports
            if report.p_max_W > 1.0
        ]
        if not rows:
            return {}
        frame = pd.DataFrame(rows)
        return frame.groupby("city")["ratio"].median().to_dict()

    def _emit_report_event(self, agent: SolarAgent, report: SolarReport, perception: Any, latency_ms: float) -> None:
        self.event_bus.emit(
            AgentEvent(
                episode_id=self.config.episode_id,
                step=report.step,
                timestamp=report.timestamp,
                agent_id=report.agent_id,
                agent_type="solar",
                event_type="solar_report",
                physical_state={
                    "city": agent.city,
                    "latitude": agent.latitude,
                    "longitude": agent.longitude,
                    "panel_area_m2": agent.panel_area_m2,
                    "efficiency": agent.efficiency,
                    "irradiance_Wm2": perception.irradiance_Wm2,
                    "air_temp_C": perception.air_temp_C,
                    "trust_score": agent.trust_score,
                    "calibration_factor": agent.calibration_factor,
                },
                reported_state=asdict(report),
                latency_ms=latency_ms,
            ),
            connected=self.config.mode == "connected_demo",
        )

    def _emit_verification_event(self, report: SolarReport, outcome: VerificationOutcome, latency_ms: float) -> None:
        self.event_bus.emit(
            AgentEvent(
                episode_id=self.config.episode_id,
                step=report.step,
                timestamp=report.timestamp,
                agent_id=report.agent_id,
                agent_type="verifier",
                event_type="verification_result",
                reported_state=asdict(report),
                verification_result=outcome.status,
                market_feedback={"verification": asdict(outcome)},
                latency_ms=latency_ms,
            ),
            audit=outcome.status != "verified",
            connected=self.config.mode == "connected_demo",
        )

    def _emit_planner_event(
        self, report: SolarReport, outcome: VerificationOutcome, decision_row: dict[str, Any], latency_ms: float
    ) -> None:
        self.event_bus.emit(
            AgentEvent(
                episode_id=self.config.episode_id,
                step=report.step,
                timestamp=report.timestamp,
                agent_id=report.agent_id,
                agent_type="planner",
                event_type="planner_decision",
                reported_state=asdict(report),
                verification_result=outcome.status,
                planner_action=decision_row["planner_action"],
                market_feedback=decision_row,
                latency_ms=latency_ms,
            ),
            audit=decision_row["planner_action"] != "approve" or decision_row["human_review_required"],
            connected=self.config.mode == "connected_demo",
        )

    def _emit_market_event(self, market_summary: MarketSummary, latency_ms: float) -> None:
        self.event_bus.emit(
            AgentEvent(
                episode_id=self.config.episode_id,
                step=market_summary.step,
                timestamp=market_summary.timestamp,
                agent_id="market-agent",
                agent_type="market",
                event_type="market_update",
                on_chain_action="settlement_ready" if self.config.mode == "connected_demo" else "",
                market_feedback=asdict(market_summary),
                latency_ms=latency_ms,
            ),
            audit=True,
            connected=True,
        )

    def _emit_feedback_event(
        self, report: SolarReport, previous_trust: float, updated_trust: float, feedback: AgentFeedback
    ) -> None:
        self.event_bus.emit(
            AgentEvent(
                episode_id=self.config.episode_id,
                step=report.step,
                timestamp=report.timestamp,
                agent_id=report.agent_id,
                agent_type="solar",
                event_type="feedback_update",
                reported_state={
                    "previous_trust": previous_trust,
                    "updated_trust": updated_trust,
                    "p_max_W": report.p_max_W,
                    "p_reported_W": report.p_reported_W,
                },
                planner_action=feedback.planner_action,
                market_feedback=asdict(feedback),
            ),
            audit=feedback.audit_flag,
            connected=self.config.mode == "connected_demo",
        )
