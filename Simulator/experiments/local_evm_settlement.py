from __future__ import annotations

import argparse
import json
import os
import string
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

from Simulator.agents.event_bus import EventBus
from Simulator.agents.types import AgentEvent, DEFAULT_EXPERIMENT_DIR, PROJECT_ROOT


DEFAULT_HARDHAT_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
CONTRACT_ADDRESS_PATH = PROJECT_ROOT / "smart_contract" / "scripts" / "contractAddress.json"
SIMULATOR_ENV_PATH = PROJECT_ROOT / "Simulator" / ".env"

ENERGY_EXCHANGE_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"internalType": "address[]", "name": "users", "type": "address[]"},
            {"internalType": "uint256[]", "name": "userEnergy", "type": "uint256[]"},
            {"internalType": "uint256", "name": "totalEnergy", "type": "uint256"},
            {"internalType": "uint256", "name": "demandEnergy", "type": "uint256"},
        ],
        "name": "updateMarketStep",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "globalSupplyEnergy",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalDemandEnergy",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def normalize_private_key(raw_key: str) -> str:
    cleaned = raw_key.strip()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) != 64 or any(ch not in string.hexdigits for ch in cleaned):
        raise ValueError("private key must be 64 hex characters, with or without 0x")
    return "0x" + cleaned.lower()


def load_addresses() -> dict[str, str]:
    with CONTRACT_ADDRESS_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_settlement_payload(output_dir: Path, preferred_step: int | None = None) -> tuple[int, str, list[str], list[int], int, int]:
    decisions = pd.read_csv(output_dir / "agent_decisions.csv")
    market = pd.read_csv(output_dir / "agent_market_summary.csv")
    approved = decisions[
        (decisions["planner_action"] == "approve")
        & (decisions[["p_reported_W", "p_max_W"]].min(axis=1) > 0)
    ].copy()
    if approved.empty:
        raise RuntimeError("no approved positive-energy agent reports found for settlement")

    step = int(preferred_step) if preferred_step is not None else int(approved["step"].max())
    approved = approved[approved["step"] == step]
    if approved.empty:
        raise RuntimeError(f"no approved positive-energy reports found at step {step}")

    market_row = market[market["step"] == step].tail(1)
    if market_row.empty:
        raise RuntimeError(f"no market summary found at step {step}")

    users = [Web3.to_checksum_address(f"0x{index + 1:040x}") for index in range(len(approved))]
    user_energy = [
        int(max(0.0, min(float(row.p_reported_W), float(row.p_max_W))))
        for row in approved.itertuples(index=False)
    ]
    total_energy = int(sum(user_energy))
    demand_energy = int(float(market_row.iloc[0]["factory_demand_W"]))
    timestamp = str(market_row.iloc[0]["timestamp"])
    return step, timestamp, users, user_energy, total_energy, demand_energy


def send_settlement_tx(
    rpc_url: str,
    private_key: str,
    users: list[str],
    user_energy: list[int],
    total_energy: int,
    demand_energy: int,
) -> dict[str, Any]:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"unable to connect to local EVM at {rpc_url}")

    exchange_address = load_addresses().get("energyExchange")
    if not exchange_address:
        raise RuntimeError(f"energyExchange missing in {CONTRACT_ADDRESS_PATH}")

    account = Account.from_key(normalize_private_key(private_key))
    exchange = w3.eth.contract(address=Web3.to_checksum_address(exchange_address), abi=ENERGY_EXCHANGE_ABI)
    tx = exchange.functions.updateMarketStep(users, user_energy, total_energy, demand_energy).build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": w3.eth.chain_id,
            "gas": 2_000_000,
        }
    )

    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas")
    if base_fee is not None:
        priority_fee = w3.eth.max_priority_fee
        tx["maxFeePerGas"] = int(base_fee * 2 + priority_fee)
        tx["maxPriorityFeePerGas"] = int(priority_fee)
    else:
        tx["gasPrice"] = w3.eth.gas_price

    signed = account.sign_transaction(tx)
    raw_tx = getattr(signed, "rawTransaction", None) or signed.raw_transaction
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise RuntimeError(f"settlement transaction reverted: {tx_hash.hex()}")

    return {
        "tx_hash": Web3.to_hex(tx_hash),
        "block_number": int(receipt.blockNumber),
        "gas_used": int(receipt.gasUsed),
        "exchange_address": exchange_address,
        "global_supply_energy": int(exchange.functions.globalSupplyEnergy().call()),
        "total_demand_energy": int(exchange.functions.totalDemandEnergy().call()),
    }


def append_settlement_event(
    output_dir: Path,
    step: int,
    timestamp: str,
    tx_result: dict[str, Any],
    users: list[str],
    user_energy: list[int],
    total_energy: int,
    demand_energy: int,
) -> AgentEvent:
    event_bus = EventBus(output_dir, reset=False)
    return event_bus.emit(
        AgentEvent(
            episode_id="eiot_month_2026_04",
            step=step,
            timestamp=timestamp,
            agent_id="energy-exchange",
            agent_type="settlement",
            event_type="on_chain_settlement",
            on_chain_action=f"local_evm_settlement_block_{tx_result['block_number']}",
            tx_hash=tx_result["tx_hash"],
            market_feedback={
                "users": users,
                "user_energy": user_energy,
                "total_energy": total_energy,
                "demand_energy": demand_energy,
                "exchange_address": tx_result["exchange_address"],
                "gas_used": tx_result["gas_used"],
                "global_supply_energy": tx_result["global_supply_energy"],
                "total_demand_energy": tx_result["total_demand_energy"],
            },
        ),
        audit=True,
        connected=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append a real local-EVM settlement tx to the SolarAgents connected trace")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    parser.add_argument("--rpc-url", default=None)
    parser.add_argument("--private-key", default=None)
    parser.add_argument("--step", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    load_dotenv(SIMULATOR_ENV_PATH)
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    rpc_url = args.rpc_url or os.getenv("SIMULATOR_RPC_URL", "http://127.0.0.1:8545")
    private_key = args.private_key or os.getenv("SIMULATOR_PRIVATE_KEY") or DEFAULT_HARDHAT_PRIVATE_KEY

    step, timestamp, users, user_energy, total_energy, demand_energy = build_settlement_payload(args.output_dir, args.step)
    tx_result = send_settlement_tx(rpc_url, private_key, users, user_energy, total_energy, demand_energy)
    event = append_settlement_event(args.output_dir, step, timestamp, tx_result, users, user_energy, total_energy, demand_energy)

    print(json.dumps(asdict(event), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
