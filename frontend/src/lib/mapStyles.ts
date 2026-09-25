// UrbanFlow — MapLibre Style Definitions & Color Utilities

import type { RiskLevel } from '@/types/flood';

// ---------------------------------------------------------------------------
// Flood risk color scale
// ---------------------------------------------------------------------------

export const RISK_COLORS: Record<RiskLevel, string> = {
  dry:        '#64748b',   // slate-500
  nuisance:   '#f59e0b',   // amber-500
  disruptive: '#f97316',   // orange-500
  severe:     '#ef4444',   // red-500
};

export const RISK_COLORS_GLOW: Record<RiskLevel, string> = {
  dry:        'rgba(100,116,139,0.0)',
  nuisance:   'rgba(245,158,11,0.4)',
  disruptive: 'rgba(249,115,22,0.6)',
  severe:     'rgba(239,68,68,0.8)',
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  dry:        'Dry',
  nuisance:   'Nuisance (5–15cm)',
  disruptive: 'Disruptive (15–30cm)',
  severe:     'Severe (>30cm)',
};

export function riskColor(level: RiskLevel): string {
  return RISK_COLORS[level] ?? RISK_COLORS.dry;
}

export function depthToRisk(depth_cm: number): RiskLevel {
  if (depth_cm < 5) return 'dry';
  if (depth_cm < 15) return 'nuisance';
  if (depth_cm < 30) return 'disruptive';
  return 'severe';
}

// ---------------------------------------------------------------------------
// MapLibre expression for road risk coloring
// ---------------------------------------------------------------------------

/**
 * Returns a MapLibre GL JS match expression that maps risk_level property
 * to the appropriate fill/line color.
 */
export function riskColorExpression() {
  return [
    'match',
    ['get', 'risk_level'],
    'dry',        RISK_COLORS.dry,
    'nuisance',   RISK_COLORS.nuisance,
    'disruptive', RISK_COLORS.disruptive,
    'severe',     RISK_COLORS.severe,
    RISK_COLORS.dry, // default
  ];
}

/**
 * Returns a MapLibre GL JS interpolate expression for line width
 * based on depth_cm (0 → 2px, 30+ → 8px).
 */
export function depthWidthExpression() {
  return [
    'interpolate',
    ['linear'],
    ['get', 'predicted_depth_cm'],
    0,  2,
    5,  3,
    15, 5,
    30, 8,
  ];
}

// ---------------------------------------------------------------------------
// Rainfall heatmap color ramp
// ---------------------------------------------------------------------------

export const RAINFALL_HEATMAP_COLOR = [
  'interpolate',
  ['linear'],
  ['heatmap-density'],
  0,   'rgba(0,0,0,0)',
  0.1, 'rgba(59,130,246,0.2)',
  0.3, 'rgba(99,102,241,0.4)',
  0.5, 'rgba(168,85,247,0.6)',
  0.8, 'rgba(239,68,68,0.7)',
  1.0, 'rgba(239,68,68,0.9)',
];

// ---------------------------------------------------------------------------
// Map center for Chennai demo
// ---------------------------------------------------------------------------

export const CHENNAI_CENTER: [number, number] = [80.26, 13.085]; // [lon, lat]
export const CHENNAI_ZOOM = 13;

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

export function formatTime(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.floor(minutes % 60);
  return `${h > 0 ? `${h}h ` : ''}${m.toString().padStart(2, '0')}min`;
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

export function formatDistance(metres: number): string {
  if (metres >= 1000) return `${(metres / 1000).toFixed(1)} km`;
  return `${Math.round(metres)} m`;
}
