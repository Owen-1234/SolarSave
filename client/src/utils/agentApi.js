import { solarApiUrl } from "./apiBase";

const request = async (path, options = {}) => {
  const response = await fetch(solarApiUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`Agent API ${response.status}: ${response.statusText}`);
  }
  return response.json();
};

export const getAgentStatus = () => request("/agents/status");

export const runAgentEpisode = (payload = {}) =>
  request("/agents/run_episode", {
    method: "POST",
    body: JSON.stringify({
      start_step: 0,
      steps: 24,
      reward_share: 0.20,
      demand_multiplier: 1.0,
      planner_policy: "balanced",
      mode: "connected_demo",
      ...payload,
    }),
  });

export const stepAgents = (payload = {}) =>
  request("/agents/step", {
    method: "POST",
    body: JSON.stringify({
      start_step: 0,
      steps: 1,
      reward_share: 0.20,
      demand_multiplier: 1.0,
      planner_policy: "balanced",
      mode: "connected_demo",
      ...payload,
    }),
  });

export const getAgentEvents = (limit = 80) =>
  request(`/agents/events?limit=${limit}`);

export const getAgentAudit = (limit = 40) =>
  request(`/agents/audit?limit=${limit}`);

export const getAgentMarketSummary = (limit = 24) =>
  request(`/agents/market_summary?limit=${limit}`);

export const settleVerifiedStep = () =>
  request("/agents/settle_verified_step", { method: "POST" });
