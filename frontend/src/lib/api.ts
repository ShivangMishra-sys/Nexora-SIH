// UrbanFlow v2 — Typed API Client
// [61] /api/v1/route, /api/v1/nowcast, /api/flood/state, /ws/flood-stream

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const WS_BASE  = process.env.NEXT_PUBLIC_WS_URL  ?? 'ws://localhost:8000';

async function fetchJSON<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getFloodState: (t?: number) =>
    fetchJSON<FloodStateAPI>(`/api/flood/state${t !== undefined ? `?t=${t}` : ''}`),

  getFloodSummary: () => fetchJSON<FloodSummary>('/api/flood/summary'),

  getNetworkGraph: () => fetchJSON<GeoJSONCollection>('/api/network/graph'),

  getBBox: () => fetchJSON<{ bbox: number[]; city: string }>('/api/network/bbox'),

  getNowcast: () => fetchJSON<NowcastAPI>('/api/v1/nowcast'),

  listSnapshots: () => fetchJSON<{ available_minutes: number[] }>('/api/snapshots'),

  computeRoute: (
    start: [number, number],
    end:   [number, number],
    vehicle_class = 'car',
  ) => fetchJSON<RouteResult>('/api/v1/route', {
    method: 'POST',
    body: JSON.stringify({ start, end, vehicle_class }),
  }),

  runScenario: (params: ScenarioParams) =>
    fetchJSON<{ status: string }>('/api/scenario/run', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  testAlert: (message: string, depth_cm: number) =>
    fetchJSON<{ status: string }>('/api/alerts/test', {
      method: 'POST',
      body: JSON.stringify({ message, depth_cm }),
    }),

  geocode: (q: string) =>
    fetchJSON<{ lat: number; lon: number; address: string } | { error: string }>(
      `/api/v1/geocode?q=${encodeURIComponent(q)}`
    ),

  retrainBlockage: () =>
    fetchJSON<{ status: string }>('/api/simulation/retrain-blockage', { method: 'POST' }),

  getValidation: () => fetchJSON<ValidationResult>('/api/validation'),
};

export function createFloodWebSocket(
  onMessage: (msg: WSFloodMessage) => void,
  onKeepalive?: () => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/ws/flood-stream`);
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'keepalive') onKeepalive?.();
      else onMessage(data);
    } catch { /* ignore parse errors */ }
  };
  ws.onerror = (e) => console.warn('[WS] error:', e);
  return ws;
}

// ── Types ──────────────────────────────────────────────────────────────────
export interface FloodNodePoint {
  lat: number; lon: number;
  depth_cm: number;
  risk: 'safe' | 'caution' | 'critical' | 'impassable';
  color: string;
}

export interface FloodStateAPI {
  t_minutes: number;
  nodes: FloodNodePoint[];
  max_depth_cm: number;
  mean_depth_cm: number;
  severe_count: number;
  critical_count: number;
  hotspots: Hotspot[];
  validation: ValidationResult;
}

export interface FloodSummary {
  max_depth_cm: number;
  mean_depth_cm: number;
  safe_pct: number;
  caution_pct: number;
  critical_pct: number;
  impassable_pct: number;
  hotspots: Hotspot[];
  validation: ValidationResult;
}

export interface Hotspot {
  cluster_id: number;
  cell_count: number;
  mean_row: number;
  mean_col: number;
  max_depth_cm: number;
  severity: 'critical' | 'caution';
}

export interface ValidationResult {
  rmse_cm?: number;
  f1_flood_detection?: number;
}

export interface GeoJSONCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: { type: string; coordinates: number[] | number[][] };
  properties: Record<string, unknown>;
}

export interface NowcastAPI {
  bbox: number[];
  forecasts_mm_hr: Record<string, { max_mm_hr: number; mean_mm_hr: number }>;
}

export interface RouteResult {
  safe_route: { coordinates: { lat: number; lon: number }[]; distance_m: number; max_depth_cm: number };
  naive_route: { coordinates: { lat: number; lon: number }[]; distance_m: number; max_depth_cm: number };
  comparison: { distance_saved_m: number; max_depth_avoided_cm: number; safe_weight_ratio: number };
  vehicle_class: string;
}

export interface ScenarioParams {
  scenario: string;
  intensity_dbz: number;
  storm_center: number[];
  radius_fraction: number;
  drain_blockage_pct: number;
}

export interface WSFloodMessage {
  type: string;
  t_minutes: number;
  max_depth_cm: number;
  mean_depth_cm: number;
  severe_count: number;
  hotspot_count: number;
  scenario: string;
}
