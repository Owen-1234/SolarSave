from __future__ import annotations

from Simulator.experiments.attack_taxonomy import run


def main() -> None:
    _, baseline = run()
    print(baseline.sort_values("f1", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
