from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FactoryAgent:
    factory_id: str
    city: str
    base_demand_W: float
    risk_tolerance: float = 1.1
    unmet_demand_history: list[float] = field(default_factory=list)

    def decide_purchase(self, available_liquidity_W: float, slippage_pct: float) -> float:
        demand = self.base_demand_W
        if slippage_pct > self.risk_tolerance:
            demand *= 0.78
        return min(demand, max(0.0, available_liquidity_W))

    def receive_feedback(self, unmet_demand_W: float) -> None:
        self.unmet_demand_history.append(float(unmet_demand_W))
        self.unmet_demand_history = self.unmet_demand_history[-48:]
