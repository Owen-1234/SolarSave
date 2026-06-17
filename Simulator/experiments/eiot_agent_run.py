from __future__ import annotations

import argparse

from Simulator.agents import CoordinationLoop, EpisodeConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the SolarAgents closed-loop EIoT episode")
    parser.add_argument("--steps", type=int, default=720)
    parser.add_argument("--start-step", type=int, default=0)
    parser.add_argument("--reward-share", type=float, default=0.25)
    parser.add_argument("--demand-multiplier", type=float, default=1.0)
    parser.add_argument("--planner-policy", choices=["strict", "balanced", "lenient"], default="balanced")
    parser.add_argument("--mode", choices=["offline_benchmark", "connected_demo"], default="connected_demo")
    parser.add_argument("--max-agents", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = CoordinationLoop(
        EpisodeConfig(
            steps=args.steps,
            start_step=args.start_step,
            reward_share=args.reward_share,
            demand_multiplier=args.demand_multiplier,
            planner_policy=args.planner_policy,
            mode=args.mode,
            max_agents=args.max_agents,
        )
    ).run()
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
