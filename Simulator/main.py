from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from SolarPVModel import SolarPVModel
import os
from dotenv import load_dotenv
import uvicorn
import asyncio
import json
import string
import pandas as pd
from web3 import Web3
from eth_account import Account
from agents import CoordinationLoop, EpisodeConfig
from agents.api_bridge import audit_events, loop_status, market_summary, recent_events
from agents.types import AgentEvent

# Load environment variables
load_dotenv()
api_key = os.getenv("SOLAR_API_KEY", "")
SIMULATOR_RPC_URL = os.getenv("SIMULATOR_RPC_URL", "http://127.0.0.1:8545")
SIMULATOR_PRIVATE_KEY = os.getenv("SIMULATOR_PRIVATE_KEY", "")
SIMULATOR_STEP_SECONDS = int(os.getenv("SIMULATOR_STEP_SECONDS", "3600"))
AGENT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "experiments")


def resolve_energy_sim_enabled(raw_value, private_key):
    lowered = (raw_value or "auto").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    # AUTO mode: enable when a plausible private key exists.
    cleaned = (private_key or "").strip()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) != 64:
        return False
    return all(ch in string.hexdigits for ch in cleaned)


ENABLE_ENERGY_SIM = resolve_energy_sim_enabled(
    os.getenv("ENABLE_ENERGY_SIM", "auto"),
    SIMULATOR_PRIVATE_KEY
)

CONTRACT_ADDRESS_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "smart_contract",
    "scripts",
    "contractAddress.json"
)

SOLAR_PANELS_ABI = [
    {
        "inputs": [],
        "name": "getAllPanels",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint256", "name": "id", "type": "uint256"},
                    {"internalType": "address", "name": "owner", "type": "address"},
                    {"internalType": "uint256", "name": "latitude", "type": "uint256"},
                    {"internalType": "uint256", "name": "longitude", "type": "uint256"},
                    {"internalType": "uint256", "name": "batteryTemperature", "type": "uint256"},
                    {"internalType": "uint256", "name": "dcPower", "type": "uint256"},
                    {"internalType": "uint256", "name": "acPower", "type": "uint256"},
                    {"internalType": "uint256", "name": "createdAt", "type": "uint256"},
                    {"internalType": "bool", "name": "exists", "type": "bool"}
                ],
                "internalType": "struct SolarPanels.Panel[]",
                "name": "",
                "type": "tuple[]"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

FACTORY_ABI = [
    {
        "inputs": [],
        "name": "getAllFactories",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint256", "name": "id", "type": "uint256"},
                    {"internalType": "address", "name": "owner", "type": "address"},
                    {"internalType": "uint256", "name": "latitude", "type": "uint256"},
                    {"internalType": "uint256", "name": "longitude", "type": "uint256"},
                    {"internalType": "uint256", "name": "powerConsumption", "type": "uint256"},
                    {"internalType": "uint256", "name": "createdAt", "type": "uint256"},
                    {"internalType": "bool", "name": "exists", "type": "bool"}
                ],
                "internalType": "struct FactoryRegistry.Factory[]",
                "name": "",
                "type": "tuple[]"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

ENERGY_EXCHANGE_ABI = [
    {
        "inputs": [],
        "name": "rewardRatioBps",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "ratio", "type": "uint256"}
        ],
        "name": "setRewardRatioBps",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address[]", "name": "users", "type": "address[]"},
            {"internalType": "uint256[]", "name": "userEnergy", "type": "uint256[]"},
            {"internalType": "uint256", "name": "totalEnergy", "type": "uint256"},
            {"internalType": "uint256", "name": "demandEnergy", "type": "uint256"}
        ],
        "name": "updateMarketStep",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "factoryId", "type": "uint256"},
            {"internalType": "uint256", "name": "energyAmount", "type": "uint256"}
        ],
        "name": "consumeFactoryEnergy",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "name": "factoryEnergyBalance",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "simulatorStepSeconds",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "stepSeconds", "type": "uint256"}
        ],
        "name": "setSimulatorStepSeconds",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Initialize FastAPI app
app = FastAPI()

def cors_origins():
    raw = os.getenv(
        "SIMULATOR_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    )
    if raw.strip() == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all HTTP headers
)


def load_contract_addresses():
    try:
        with open(CONTRACT_ADDRESS_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def normalize_private_key(raw_key):
    if not raw_key:
        return None, "SIMULATOR_PRIVATE_KEY is not set"

    cleaned = raw_key.strip()
    if not cleaned or "<" in cleaned or ">" in cleaned:
        return None, "SIMULATOR_PRIVATE_KEY is not set to a real private key"

    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]

    if len(cleaned) != 64:
        return None, "SIMULATOR_PRIVATE_KEY must be 64 hex characters (with or without 0x prefix)"

    if any(ch not in string.hexdigits for ch in cleaned):
        return None, "SIMULATOR_PRIVATE_KEY contains non-hex characters"

    return "0x" + cleaned.lower(), None


def build_web3():
    normalized_key, error = normalize_private_key(SIMULATOR_PRIVATE_KEY)
    if error:
        print(f"Energy simulator disabled: {error}")
        return None, None

    w3 = Web3(Web3.HTTPProvider(SIMULATOR_RPC_URL))
    if not w3.is_connected():
        print("Energy simulator disabled: unable to connect to RPC")
        return None, None

    account = Account.from_key(normalized_key)
    return w3, account


def send_transaction(w3, account, tx, nonce):
    tx.update({
        "nonce": nonce,
        "gas": tx.get("gas", 500000),
        "chainId": w3.eth.chain_id
    })

    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas")
    if base_fee is not None:
        max_priority_fee = w3.eth.max_priority_fee
        tx.update({
            "maxFeePerGas": int(base_fee * 2 + max_priority_fee),
            "maxPriorityFeePerGas": int(max_priority_fee)
        })
    else:
        tx.update({
            "gasPrice": w3.eth.gas_price
        })
    signed = account.sign_transaction(tx)
    raw_tx = getattr(signed, "rawTransaction", None) or signed.raw_transaction
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    w3.eth.wait_for_transaction_receipt(tx_hash)
    return nonce + 1


def calculate_market_step(panels, factories):
    total_dc = 0
    user_dc = {}
    total_demand = 0

    for panel in panels:
        dc_power = panel[5]
        total_dc += dc_power
        owner = panel[1]
        user_dc[owner] = user_dc.get(owner, 0) + dc_power

    for factory in factories:
        total_demand += factory[4]

    users = []
    user_energy = []
    for owner, dc_power in user_dc.items():
        if dc_power > 0:
            users.append(owner)
            user_energy.append(dc_power)

    return users, user_energy, total_dc, total_demand


async def market_loop():
    w3, account = build_web3()
    if not w3 or not account:
        print("Energy simulator disabled: missing RPC or private key")
        return

    addresses = load_contract_addresses()
    panels_address = addresses.get("solarPanels")
    factory_address = addresses.get("factory")
    exchange_address = addresses.get("energyExchange")

    if not panels_address or not factory_address or not exchange_address:
        print("Energy simulator disabled: missing contract addresses")
        return

    panels_contract = w3.eth.contract(address=panels_address, abi=SOLAR_PANELS_ABI)
    factory_contract = w3.eth.contract(address=factory_address, abi=FACTORY_ABI)
    exchange_contract = w3.eth.contract(address=exchange_address, abi=ENERGY_EXCHANGE_ABI)

    configured_step_seconds = max(1, SIMULATOR_STEP_SECONDS)

    def sync_step_seconds_if_needed(nonce=None):
        try:
            chain_step = exchange_contract.functions.simulatorStepSeconds().call()
            if chain_step == configured_step_seconds:
                return nonce

            local_nonce = nonce
            if local_nonce is None:
                local_nonce = w3.eth.get_transaction_count(account.address, "pending")

            set_step_tx = exchange_contract.functions.setSimulatorStepSeconds(
                configured_step_seconds
            ).build_transaction({
                "from": account.address
            })
            next_nonce = send_transaction(w3, account, set_step_tx, local_nonce)
            print(
                f"Energy simulator step synced: chain {chain_step}s -> local {configured_step_seconds}s"
            )
            return next_nonce
        except Exception as exc:
            print(f"Energy simulator step sync skipped: {exc}")
            return nonce

    sync_step_seconds_if_needed()

    loop = asyncio.get_running_loop()
    next_tick_at = loop.time()

    while True:
        try:
            panels = panels_contract.functions.getAllPanels().call()
            factories = factory_contract.functions.getAllFactories().call()

            users, user_energy, total_energy, total_demand = calculate_market_step(panels, factories)

            nonce = w3.eth.get_transaction_count(account.address, "pending")
            nonce = sync_step_seconds_if_needed(nonce)
            update_tx = exchange_contract.functions.updateMarketStep(
                users,
                user_energy,
                total_energy,
                total_demand
            ).build_transaction({
                "from": account.address
            })
            nonce = send_transaction(w3, account, update_tx, nonce)

            for factory in factories:
                factory_id = factory[0]
                consumption = factory[4]
                balance = exchange_contract.functions.factoryEnergyBalance(factory_id).call()
                if balance == 0:
                    continue
                to_consume = consumption if balance >= consumption else balance
                if to_consume == 0:
                    continue
                consume_tx = exchange_contract.functions.consumeFactoryEnergy(
                    factory_id,
                    to_consume
                ).build_transaction({
                    "from": account.address
                })
                nonce = send_transaction(w3, account, consume_tx, nonce)
            next_tick_at += configured_step_seconds
        except Exception as exc:
            print(f"Energy simulator step failed: {exc}")
            # Retry quickly after failures instead of waiting a full cycle.
            next_tick_at = loop.time() + min(5, configured_step_seconds)

        await asyncio.sleep(max(0, next_tick_at - loop.time()))


@app.on_event("startup")
async def startup_event():
    if ENABLE_ENERGY_SIM:
        print("Energy simulator loop started")
        asyncio.create_task(market_loop())
    else:
        print("Energy simulator loop disabled (set ENABLE_ENERGY_SIM=true to force enable)")

# Define input models
class SolarRequest(BaseModel):
    lat: float
    lon: float
    start_date: str
    end_date: Optional[str] = None
    freq: str = "60min"

class MultiSolarRequest(BaseModel):
    coordinates: List[dict]
    start_date: str
    end_date: Optional[str] = None
    freq: str = "60min"


class AgentEpisodeRequest(BaseModel):
    start_step: int = 0
    steps: int = 24
    reward_share: float = 0.20
    demand_multiplier: float = 1.0
    planner_policy: str = "balanced"
    mode: str = "connected_demo"
    max_agents: Optional[int] = None


AGENT_LOOP: Optional[CoordinationLoop] = None


def agent_config_from_request(request: AgentEpisodeRequest) -> EpisodeConfig:
    return EpisodeConfig(
        start_step=request.start_step,
        steps=request.steps,
        reward_share=request.reward_share,
        demand_multiplier=request.demand_multiplier,
        planner_policy=request.planner_policy,
        mode=request.mode,
        max_agents=request.max_agents,
    )


def ensure_agent_loop(request: Optional[AgentEpisodeRequest] = None) -> CoordinationLoop:
    global AGENT_LOOP
    if AGENT_LOOP is None or request is not None:
        AGENT_LOOP = CoordinationLoop(agent_config_from_request(request or AgentEpisodeRequest()))
    return AGENT_LOOP


@app.get("/agents/status")
async def agents_status():
    return loop_status(AGENT_LOOP)


@app.post("/agents/step")
async def agents_step(request: AgentEpisodeRequest):
    loop = ensure_agent_loop(request)
    timestamps = loop.environment.timestamps(request.start_step, 1)
    if not timestamps:
        return {"status": "error", "message": "start_step is outside the monthly dataset"}
    result = loop.step(timestamps[0], request.start_step)
    return {
        "status": "success",
        "market_summary": result["market_summary"].__dict__,
        "decisions": loop.last_decisions[:10],
        "events_written": len(loop.event_bus.events),
    }


@app.post("/agents/run_episode")
async def agents_run_episode(request: AgentEpisodeRequest):
    loop = ensure_agent_loop(request)
    result = loop.run()
    return {"status": "success", **result}


@app.get("/agents/events")
async def agents_events(limit: int = 100):
    return {"status": "success", "events": recent_events(AGENT_OUTPUT_DIR, limit)}


@app.get("/agents/audit")
async def agents_audit(limit: int = 100):
    return {"status": "success", "events": audit_events(AGENT_OUTPUT_DIR, limit)}


@app.get("/agents/market_summary")
async def agents_market_summary(limit: int = 24):
    return {"status": "success", "market_summary": market_summary(AGENT_OUTPUT_DIR, limit)}


@app.post("/agents/settle_verified_step")
async def agents_settle_verified_step():
    loop = ensure_agent_loop()
    if loop.last_market_summary is None:
        request = AgentEpisodeRequest(steps=1, mode="connected_demo")
        loop = ensure_agent_loop(request)
        timestamp = loop.environment.timestamps(0, 1)[0]
        loop.step(timestamp, 0)

    approved = [row for row in loop.last_decisions if row["planner_action"] == "approve"]
    market = loop.last_market_summary
    if not any(min(row["p_reported_W"], row["p_max_W"]) > 0 for row in approved):
        decisions_path = os.path.join(AGENT_OUTPUT_DIR, "agent_decisions.csv")
        market_path = os.path.join(AGENT_OUTPUT_DIR, "agent_market_summary.csv")
        if os.path.exists(decisions_path) and os.path.exists(market_path):
            decisions_frame = pd.read_csv(decisions_path)
            market_frame = pd.read_csv(market_path)
            approved_frame = decisions_frame[
                (decisions_frame["planner_action"] == "approve")
                & (decisions_frame[["p_reported_W", "p_max_W"]].min(axis=1) > 0)
            ]
            if not approved_frame.empty:
                fallback_step = int(approved_frame["step"].max())
                approved = approved_frame[approved_frame["step"] == fallback_step].to_dict("records")
                market_row = market_frame[market_frame["step"] == fallback_step].tail(1)
                if not market_row.empty:
                    market = type("MarketDTO", (), market_row.iloc[0].to_dict())()

    users = []
    user_energy = []
    for index, row in enumerate(approved):
        users.append(Web3.to_checksum_address(f"0x{index + 1:040x}"))
        user_energy.append(int(max(0, min(row["p_reported_W"], row["p_max_W"]))))

    total_energy = int(sum(user_energy))
    demand_energy = int(market.factory_demand_W if market else 0)
    tx_hash = ""
    on_chain_action = "settlement_skipped_no_chain"

    w3, account = build_web3()
    if w3 and account:
        addresses = load_contract_addresses()
        exchange_address = addresses.get("energyExchange")
        if exchange_address:
            exchange_contract = w3.eth.contract(address=exchange_address, abi=ENERGY_EXCHANGE_ABI)
            nonce = w3.eth.get_transaction_count(account.address, "pending")
            tx = exchange_contract.functions.updateMarketStep(
                users,
                user_energy,
                total_energy,
                demand_energy,
            ).build_transaction({"from": account.address})
            before_nonce = nonce
            nonce = send_transaction(w3, account, tx, nonce)
            latest_block = w3.eth.get_block("latest", full_transactions=True)
            tx_hash = latest_block.transactions[-1].hash.hex() if latest_block.transactions else ""
            on_chain_action = f"local_evm_settlement_nonce_{before_nonce}_{nonce}"

    if not tx_hash:
        tx_hash = Web3.keccak(text=json.dumps({
            "users": users,
            "user_energy": user_energy,
            "total_energy": total_energy,
            "demand_energy": demand_energy,
            "mode": "simulated_audit_hash",
        }, sort_keys=True)).hex()
        on_chain_action = "simulated_settlement_hash_no_rpc"

    loop.event_bus.emit(
        AgentEvent(
            episode_id=loop.config.episode_id,
            step=market.step if market else 0,
            timestamp=market.timestamp if market else "",
            agent_id="energy-exchange",
            agent_type="settlement",
            event_type="on_chain_settlement",
            on_chain_action=on_chain_action,
            tx_hash=tx_hash,
            market_feedback={
                "users": users,
                "user_energy": user_energy,
                "total_energy": total_energy,
                "demand_energy": demand_energy,
            },
        ),
        audit=True,
        connected=True,
    )
    return {
        "status": "success",
        "on_chain_action": on_chain_action,
        "tx_hash": tx_hash,
        "approved_agents": len(approved),
        "total_energy": total_energy,
        "demand_energy": demand_energy,
    }

@app.post("/run_model/")
async def run_model(request: SolarRequest):
    try:
        solar_model = SolarPVModel(
            lat=request.lat,
            lon=request.lon,
            api_key=api_key
        )
        if request.end_date:
            results = solar_model.run_model_for_time_range(
                start_date=request.start_date,
                end_date=request.end_date,
                freq=request.freq
            )
        else:
            results = solar_model.run_model(
                start_date=request.start_date,
                periods=24,
                freq=request.freq
            )

        return {
            "status": "success",
            "data": {
                "aoi": results["aoi"],
                "cell_temperature": results["cell_temperature"],
                # FIXED: 提取 p_mp (功率) 而不是 v_mp (电压)
                "dc_power": results["dc"]["p_mp"],  
                "ac": results["ac"],
            },
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/run_combined_model/")
async def run_combined_model(request: MultiSolarRequest):
    combined_ac = 0
    combined_dc = 0
    results = []

    try:
        for coord in request.coordinates:
            lat, lon = coord["lat"], coord["lon"]
            solar_model = SolarPVModel(lat, lon, api_key)

            if request.end_date:
                model_results = solar_model.run_model_for_time_range(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    freq=request.freq
                )
            else:
                model_results = solar_model.run_model(
                    start_date=request.start_date,
                    periods=24,
                    freq=request.freq
                )

            ac_power = model_results["ac"].sum() if model_results["ac"] is not None else 0
            
            # FIXED: 聚合 p_mp (功率) 而不是 v_mp (电压)
            dc_power = model_results["dc"]["p_mp"].sum() if "p_mp" in model_results["dc"] else 0

            combined_ac += ac_power
            combined_dc += dc_power

            results.append({
                "lat": lat,
                "lon": lon,
                # FIXED: 返回 p_mp
                "dc_power": model_results["dc"]["p_mp"], 
                "ac": model_results["ac"],
            })

        return {
            "status": "success",
            "combined_ac": combined_ac,
            "combined_dc": combined_dc,
            "details": results,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/")
async def root():
    return {"message": "SolarPVModel API is running!"}

if __name__ == '__main__':
    # 运行fastapi程序
    uvicorn.run(app="main:app", host="0.0.0.0", port=8000, reload=True)
