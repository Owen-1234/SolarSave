# SolarChain-Eval Monthly Dataset Import

Source: `/Users/oushilin/Desktop/Solar_RL/SolarChain-Eval/data/datasets_2026_04_month`

Imported into SolarSave on 2026-06-16.

## Scope

- Date range: 2026-04-01 to 2026-05-01, hourly, Asia/Shanghai
- Cities: Beijing, Shanghai, Chengdu, Shenzhen, Hangzhou
- Nodes: 50 total, 10 per city
- Generation records: 36,000 rows
- Market records: 720 hourly rows
- Default reward/liquidity split: 20% / 80%, selected by `Simulator/experiments/ratio_sweep.py`

## Files

- `urban_energy_nodes.csv`: five-city DER node metadata
- `spatiotemporal_generation.csv`: hourly physical generation, reported generation, and FDIA labels
- `market_liquidity.csv`: hourly verified supply, mechanism-driven reward/liquidity split, demand fulfillment, unmet demand, and slippage metrics
- `p2p_trades.csv`: synthetic factory purchase records

## Generation Code

The generator was imported to:

`Simulator/data/generate_monthly_datasets.py`

The matching Open-Meteo weather cache was imported to:

`Simulator/data/cache/open_meteo_weather_2026-04-01_2026-05-01.json`

Run from the SolarSave root:

```bash
python Simulator/data/generate_monthly_datasets.py
```

To regenerate with the selected split explicitly:

```bash
python Simulator/data/generate_monthly_datasets.py --reward-share 0.20
```
