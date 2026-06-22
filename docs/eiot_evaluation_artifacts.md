# EIoT Evaluation Artifacts

This note maps the repository outputs to the paper claims that are safest for an
EIoT workshop submission.

## Residual Memory Definition

For each solar agent `i` at step `t`, the simulator stores a residual history

```text
r_i,t = (P_reported_i,t - P_expected_i,t) / max(P_max_i,t, 1)
```

The trust-memory detector flags persistent daylight bias when a rolling
24-step residual mean or absolute residual mean stays large and the current
report has the same direction. The implementation is in
`Simulator/experiments/common.py::detector_residual_memory`, and the agent-side
state update is in `Simulator/agents/solar_agent.py::receive_feedback`.

The ablation table `Simulator/data/experiments/adaptive_memory_delta.csv`
compares each adaptive variant against `static_physics_bound` so the paper can
state where memory helps, where it is neutral, and where it should not be
overclaimed.

## Threshold Sensitivity

`Simulator/experiments/tolerance_sweep.py` sweeps the physics-bound tolerance
from `1.00` to `1.08` and writes:

- `tolerance_sweep_results.csv`: per-attack precision, recall, false
  acceptance, and false rejection.
- `tolerance_sweep_summary.csv`: macro metrics plus dataset, above-bound, and
  near-bound recall by tolerance.

This supports a PR-style analysis without changing the verifier itself.

## Capability Boundary

`Simulator/experiments/attack_capability_boundary.py` summarizes the
`adaptive-solaragent` detector as:

- `strongly_covered`: safe to claim as covered by current screening.
- `partially_covered`: claim as screening/audit evidence, not full defense.
- `outside_current_claim`: explicitly present as a limitation.

This is the preferred source for paper wording around near-bound,
within-bound, weather-spoofing, and coordinated stealth attacks.

## Auditability

`Simulator/experiments/verify_event_chain.py` recomputes every event hash from
the serialized event payload and checks that each `previous_hash` matches the
prior event. The output `event_chain_verification.csv` is the artifact to cite
for the verifiable settlement/audit claim.

## Dataset Provenance

`Simulator/experiments/build_dataset_provenance.py` writes
`Simulator/data/datasets_2026_04_month/dataset_provenance.json`, including the
time window, city/node counts, generation script, Open-Meteo weather cache
files, pvlib modeling path, FDIA injection rules, and selected reward/liquidity
ratio source.
