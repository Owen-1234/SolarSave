from __future__ import annotations

from Simulator.experiments import adaptive_verification, attack_taxonomy, ratio_sweep, scale_benchmark, system_overhead
from Simulator.experiments.eiot_agent_run import main as run_agent_main


def main() -> None:
    print("Running SolarAgents 720h connected-demo episode")
    run_agent_main()
    print("Running attack taxonomy")
    attack_taxonomy.run()
    print("Running adaptive verification")
    adaptive_verification.run()
    print("Running ratio sweep")
    ratio_sweep.run()
    print("Running system overhead")
    system_overhead.run()
    print("Running scale benchmark")
    scale_benchmark.run()
    print("All EIoT experiment outputs written to Simulator/data/experiments")


if __name__ == "__main__":
    main()
