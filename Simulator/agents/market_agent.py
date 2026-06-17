from __future__ import annotations

from dataclasses import dataclass

from .factory_agent import FactoryAgent
from .types import MarketSummary


@dataclass
class MarketAgent:
    reward_share: float = 0.20
    reserve_buffer_W: float = 18_000.0
    slippage_epsilon_W: float = 45_000.0

    @property
    def liquidity_share(self) -> float:
        return max(0.0, 1.0 - self.reward_share)

    def settle(
        self,
        timestamp: str,
        step: int,
        approved_supply_W: float,
        factory_demand_W: float,
        approved_agents: int,
        rejected_agents: int,
        escalated_agents: int,
    ) -> MarketSummary:
        reward_energy_W = approved_supply_W * self.reward_share
        liquidity_energy_W = approved_supply_W * self.liquidity_share + self.reserve_buffer_W
        fulfilled_demand_W = min(factory_demand_W, liquidity_energy_W)
        unmet_demand_W = max(0.0, factory_demand_W - fulfilled_demand_W)
        slippage_pct = 100.0 * fulfilled_demand_W / (liquidity_energy_W + self.slippage_epsilon_W)

        return MarketSummary(
            timestamp=timestamp,
            step=step,
            reward_share=self.reward_share,
            liquidity_share=self.liquidity_share,
            verified_supply_W=approved_supply_W,
            reward_energy_W=reward_energy_W,
            liquidity_energy_W=liquidity_energy_W,
            factory_demand_W=factory_demand_W,
            fulfilled_demand_W=fulfilled_demand_W,
            unmet_demand_W=unmet_demand_W,
            slippage_pct=slippage_pct,
            approved_agents=approved_agents,
            rejected_agents=rejected_agents,
            escalated_agents=escalated_agents,
        )


def build_factory_agents() -> list[FactoryAgent]:
    return [
        FactoryAgent("FAC-BJ-01", "Beijing", 9_000.0),
        FactoryAgent("FAC-SH-01", "Shanghai", 12_500.0),
        FactoryAgent("FAC-CD-01", "Chengdu", 8_500.0),
        FactoryAgent("FAC-SZ-01", "Shenzhen", 11_000.0),
        FactoryAgent("FAC-HZ-01", "Hangzhou", 9_800.0),
        FactoryAgent("FAC-SH-02", "Shanghai", 10_000.0),
    ]
