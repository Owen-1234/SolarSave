from __future__ import annotations

from dataclasses import dataclass

from .types import PlannerDecision, SolarReport, VerificationOutcome


@dataclass
class PlannerAgent:
    planner_id: str = "planner-urban-energy"
    policy: str = "balanced"

    def decide(self, report: SolarReport, outcome: VerificationOutcome, trust_score: float) -> PlannerDecision:
        if outcome.status == "rejected":
            return PlannerDecision("reject", outcome.reason, True, self.policy)

        if self.policy == "strict":
            if outcome.status == "suspect" or trust_score < 0.65:
                return PlannerDecision("reject", f"strict_policy_{outcome.reason}", True, self.policy)
            return PlannerDecision("approve", "strict_policy_verified", False, self.policy)

        if self.policy == "lenient":
            if outcome.risk_level == "high" and trust_score < 0.45:
                return PlannerDecision("escalate", f"lenient_high_risk_{outcome.reason}", True, self.policy)
            return PlannerDecision("approve", "lenient_policy_approved", outcome.status == "suspect", self.policy)

        if outcome.status == "suspect" and trust_score < 0.55:
            return PlannerDecision("escalate", f"balanced_low_trust_{outcome.reason}", True, self.policy)
        if outcome.risk_level == "medium" and outcome.false_acceptance_risk > 0.5:
            return PlannerDecision("escalate", f"balanced_residual_review_{outcome.reason}", True, self.policy)
        return PlannerDecision("approve", f"balanced_{outcome.reason}", outcome.status == "suspect", self.policy)
