// UrbanFlow — Shared TypeScript Types

export type RiskLevel = 'dry' | 'nuisance' | 'disruptive' | 'severe';

export interface FloodNode {
  node_id: string;
  lat: number;
  lon: number;
  elevation_m: number;
  predicted_depth_cm: number;
  risk_level: RiskLevel;
  eta_minutes: number;
  confidence: number;
  rainfall_mm_hr: number;
  drainage_util_pct: number;
  clogging_idx: number;
}

export interface FloodSummary {
  mean_depth_cm: number;
  max_depth_cm: number;
  severe_count: number;
  disruptive_count: number;
  nuisance_count: number;
  dry_count: number;
  drainage_util_pct: number;
}

export interface FloodState {
  t_minutes: number;
  run_id: string;
  scenario_name: string;
  storm_center: { lat: number; lon: number };
  summary: FloodSummary;
  nodes: FloodNode[];
}

export interface ScenarioInfo {
  name: string;
  peak_intensity_mm_hr: number;
  radius_km: number;
  duration_minutes: number;
  description: string;
}

export interface SimStatus {
  is_running: boolean;
  is_paused: boolean;
  sim_clock_min: number;
  run_id: string | null;
  scenario: string | null;
  node_count: number;
  edge_count: number;
  intensity_timeseries: IntensityPoint[];
}

export interface IntensityPoint {
  t_minutes: number;
  mean_mm_hr: number;
  max_mm_hr: number;
  storm_lat: number;
  storm_lon: number;
}

export interface RouteCoord {
  lat: number;
  lon: number;
}

export interface RouteDetails {
  coordinates: RouteCoord[];
  travel_time_s: number;
  distance_m: number;
  node_ids: string[];
}

export interface RouteComparison {
  time_saved_s: number;
  time_saved_pct: number;
  flooded_edges_avoided: number;
  severe_edges_avoided: number;
  disruptive_edges_avoided: number;
}

export interface RouteResult {
  start: { lat: number; lon: number };
  end: { lat: number; lon: number };
  safe_route: RouteDetails;
  naive_route: RouteDetails;
  comparison: RouteComparison;
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: {
    type: 'Point' | 'LineString';
    coordinates: number[] | number[][];
  };
  properties: Record<string, unknown>;
}

export interface GeoJSONFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

export interface BBox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

export interface BBoxInfo {
  city: string;
  bbox: BBox;
  center: { lat: number; lon: number };
}

// Map interaction state
export interface MapPin {
  lat: number;
  lon: number;
}

export type RouteSelectionState =
  | { step: 'idle' }
  | { step: 'selecting_start' }
  | { step: 'selecting_end'; start: MapPin }
  | { step: 'computing'; start: MapPin; end: MapPin }
  | { step: 'done'; start: MapPin; end: MapPin; result: RouteResult };
