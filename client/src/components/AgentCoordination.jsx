import React, { useEffect, useState } from "react";
import { Gauge, RefreshCw } from "lucide-react";
import { getAgentMarketSummary } from "../utils/agentApi";

const fmtMw = (value) => `${(Number(value || 0) / 1_000_000).toFixed(3)} MW`;

const AgentCoordination = () => {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");

  const refresh = async () => {
    try {
      const payload = await getAgentMarketSummary(24);
      setRows(payload.market_summary || []);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const latest = rows.at(-1);

  return (
    <div className="planner-panel agent-coordination-panel">
      <div className="planner-panel-header compact">
        <div>
          <h3>Agent Coordination</h3>
          <p>Market feedback from approved embodied solar reports.</p>
        </div>
        <button type="button" className="agent-icon-button" onClick={refresh} title="Refresh market feedback">
          <RefreshCw size={16} />
        </button>
      </div>

      {latest ? (
        <div className="planner-metrics agent-coordination-metrics">
          <div><Gauge size={16} /><strong>{fmtMw(latest.verified_supply_W)}</strong><span>verified supply</span></div>
          <div><strong>{fmtMw(latest.liquidity_energy_W)}</strong><span>market liquidity</span></div>
          <div><strong>{fmtMw(latest.factory_demand_W)}</strong><span>factory demand</span></div>
          <div><strong>{Number(latest.slippage_pct || 0).toFixed(2)}%</strong><span>slippage</span></div>
        </div>
      ) : (
        <p className="planner-empty">{error || "Run an agent episode to populate coordination metrics."}</p>
      )}
    </div>
  );
};

export default AgentCoordination;
