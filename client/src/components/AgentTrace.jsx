import React, { useEffect, useMemo, useState } from "react";
import { Activity, RefreshCw, Route, ShieldCheck, Zap } from "lucide-react";
import {
  getAgentAudit,
  getAgentEvents,
  getAgentMarketSummary,
  getAgentStatus,
  runAgentEpisode,
  settleVerifiedStep,
} from "../utils/agentApi";

const eventLabel = (event) =>
  `${event.step ?? "-"} · ${event.event_type || "event"} · ${event.agent_id || "system"}`;

const compactNumber = (value) => {
  const numeric = Number(value || 0);
  if (Math.abs(numeric) >= 1_000_000) return `${(numeric / 1_000_000).toFixed(3)} MW`;
  if (Math.abs(numeric) >= 1_000) return `${(numeric / 1_000).toFixed(2)} kW`;
  return numeric.toFixed(1);
};

const AgentTrace = () => {
  const [status, setStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [audit, setAudit] = useState([]);
  const [market, setMarket] = useState([]);
  const [selected, setSelected] = useState(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState("");
  const [settlement, setSettlement] = useState(null);

  const refresh = async () => {
    const [statusPayload, eventsPayload, auditPayload, marketPayload] = await Promise.all([
      getAgentStatus(),
      getAgentEvents(100),
      getAgentAudit(60),
      getAgentMarketSummary(24),
    ]);
    setStatus(statusPayload);
    setEvents(eventsPayload.events || []);
    setAudit(auditPayload.events || []);
    setMarket(marketPayload.market_summary || []);
  };

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);

  const selectedFeedback = useMemo(() => {
    if (!selected?.reported_state) return null;
    const reported = selected.reported_state;
    const feedback = selected.market_feedback || {};
    return {
      previousTrust: reported.previous_trust,
      updatedTrust: reported.updated_trust,
      plannerAction: selected.planner_action || feedback.planner_action,
      txHash: selected.tx_hash,
    };
  }, [selected]);

  const runEpisode = async () => {
    setIsBusy(true);
    setError("");
    try {
      await runAgentEpisode({ steps: 24, mode: "connected_demo" });
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsBusy(false);
    }
  };

  const settle = async () => {
    setIsBusy(true);
    setError("");
    try {
      const result = await settleVerifiedStep();
      setSettlement(result);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="planner-panel agent-trace-panel">
      <div className="planner-panel-header">
        <div>
          <h3>SolarAgents Trace</h3>
          <p>{status?.dataset ? `${status.dataset.nodes} agents · ${status.dataset.timestamps} hourly steps · ${status.dataset.fdia_rows} FDIA labels` : "Agent service not initialized"}</p>
        </div>
        <span className="planner-badge">{events.length} events</span>
      </div>

      <div className="agent-actions">
        <button type="button" onClick={runEpisode} disabled={isBusy} title="Run 24-hour connected agent episode">
          <Route size={16} /> Run 24h
        </button>
        <button type="button" onClick={settle} disabled={isBusy} title="Settle approved agent supply">
          <Zap size={16} /> Settle
        </button>
        <button type="button" onClick={() => refresh().catch((err) => setError(err.message))} disabled={isBusy} title="Refresh agent trace">
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {error && <p className="planner-empty agent-error">{error}</p>}

      <div className="agent-trace-grid">
        <div className="agent-event-list">
          {events.slice().reverse().map((event, index) => (
            <button
              type="button"
              key={`${event.record_hash || index}-${event.event_type}`}
              className={`agent-event-row ${selected?.record_hash === event.record_hash ? "active" : ""}`}
              onClick={() => setSelected(event)}
            >
              <span><Activity size={14} /> {eventLabel(event)}</span>
              <small>{event.verification_result || event.planner_action || event.on_chain_action || "logged"}</small>
            </button>
          ))}
        </div>

        <div className="agent-detail">
          {selected ? (
            <>
              <div className="agent-detail-title">
                <ShieldCheck size={18} />
                <strong>{eventLabel(selected)}</strong>
              </div>
              <div className="planner-evidence-grid">
                <div><span>P_max</span><strong>{compactNumber(selected.reported_state?.p_max_W)}</strong></div>
                <div><span>P_reported</span><strong>{compactNumber(selected.reported_state?.p_reported_W)}</strong></div>
                <div><span>Previous Trust</span><strong>{selectedFeedback?.previousTrust ?? "n/a"}</strong></div>
                <div><span>Updated Trust</span><strong>{selectedFeedback?.updatedTrust ?? "n/a"}</strong></div>
              </div>
              {selected.tx_hash && <small className="audit-hash">{selected.tx_hash.slice(0, 14)}...{selected.tx_hash.slice(-8)}</small>}
            </>
          ) : (
            <p className="planner-empty">Select an agent event to inspect trust, verification, and settlement feedback.</p>
          )}
        </div>
      </div>

      <div className="agent-market-strip">
        <span>Latest liquidity: <strong>{compactNumber(market.at(-1)?.liquidity_energy_W)}</strong></span>
        <span>Unmet demand: <strong>{compactNumber(market.at(-1)?.unmet_demand_W)}</strong></span>
        <span>Audit events: <strong>{audit.length}</strong></span>
        {settlement?.tx_hash && <span>Settlement: <strong>{settlement.tx_hash.slice(0, 10)}...</strong></span>}
      </div>
    </div>
  );
};

export default AgentTrace;
