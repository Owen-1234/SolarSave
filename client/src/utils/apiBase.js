export const SOLAR_API_BASE =
  import.meta.env.VITE_SOLAR_AGENT_API || "http://localhost:8000";

export const solarApiUrl = (path) => `${SOLAR_API_BASE}${path}`;
