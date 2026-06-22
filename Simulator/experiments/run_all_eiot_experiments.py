from __future__ import annotations

from Simulator.experiments import (
    adaptive_verification,
    attack_capability_boundary,
    attack_taxonomy,
    build_dataset_provenance,
    ratio_sweep,
    scale_benchmark,
    system_overhead,
    tolerance_sweep,
    verify_event_chain,
)
from Simulator.experiments.eiot_agent_run import main as run_agent_main


def main() -> None:
    print("Running SolarAgents 720h connected-demo episode")
    run_agent_main()
    print("Running attack taxonomy")
    taxonomy, _ = attack_taxonomy.run()
    print("Building attack capability boundary")
    attack_capability_boundary.run(taxonomy)
    print("Running adaptive verification")
    adaptive_verification.run()
    print("Running tolerance sensitivity sweep")
    tolerance_sweep.run()
    print("Running ratio sweep")
    ratio_sweep.run()
    print("Running system overhead")
    system_overhead.run()
    print("Running scale benchmark")
    scale_benchmark.run()
    print("Building dataset provenance metadata")
    build_dataset_provenance.run()
    print("Verifying event hash chain")
    verify_event_chain.run()
    print("All EIoT experiment outputs written to Simulator/data/experiments")


if __name__ == "__main__":
    main()
