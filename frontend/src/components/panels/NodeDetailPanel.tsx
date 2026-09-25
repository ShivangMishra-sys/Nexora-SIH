'use client';

import type { FloodNode } from '@/types/flood';
import { RISK_COLORS, RISK_LABELS } from '@/lib/mapStyles';
import { X, Droplets, CloudRain, AlertTriangle } from 'lucide-react';

interface NodeDetailPanelProps {
  node: FloodNode | null;
  hoveredProps: Record<string, unknown> | null;
  onClose: () => void;
}

function RiskBadge({ level }: { level: string }) {
  const colors: Record<string, string> = {
    dry:        'bg-slate-500/20 text-slate-300 border-slate-500/30',
    nuisance:   'bg-amber-500/20 text-amber-300 border-amber-500/30',
    disruptive: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
    severe:     'bg-red-500/20 text-red-300 border-red-500/30',
  };
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-semibold uppercase tracking-wide ${colors[level] ?? colors.dry}`}>
      {level}
    </span>
  );
}

function StatRow({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex justify-between items-center py-1 border-b border-surface-border/50">
      <span className="text-xs text-muted">{label}</span>
      <span className="text-xs font-mono text-white">
        {value}{unit ? <span className="text-muted ml-0.5">{unit}</span> : null}
      </span>
    </div>
  );
}

export default function NodeDetailPanel({ node, hoveredProps, onClose }: NodeDetailPanelProps) {
  // Use hovered props if no selected node
  const props = node
    ? { ...node }
    : hoveredProps
      ? {
          node_id:             hoveredProps.node_id as string,
          risk_level:          hoveredProps.risk_level as string,
          predicted_depth_cm:  hoveredProps.predicted_depth_cm as number,
          rainfall_mm_hr:      hoveredProps.rainfall_mm_hr as number,
          eta_minutes:         hoveredProps.eta_minutes as number,
          confidence:          hoveredProps.confidence as number,
          clogging_idx:        hoveredProps.clogging_idx as number,
          drainage_util_pct:   0,
          elevation_m:         0,
          lat:                 0,
          lon:                 0,
        }
      : null;

  if (!props) return null;

  const isHover = !node && hoveredProps;
  const depthColor = RISK_COLORS[props.risk_level as keyof typeof RISK_COLORS] ?? '#64748b';

  return (
    <div className="w-72 bg-surface-card/95 backdrop-blur-sm rounded-xl border border-surface-border shadow-xl animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
        <div className="flex items-center gap-2">
          <div
            className="w-2.5 h-2.5 rounded-full ring-2 ring-offset-1 ring-offset-surface-card"
            style={{ background: depthColor, boxShadow: `0 0 8px ${depthColor}` }}
          />
          <span className="text-sm font-semibold text-white">
            {isHover ? 'Node Info' : 'Selected Node'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <RiskBadge level={props.risk_level} />
          {node && (
            <button onClick={onClose} className="text-muted hover:text-white transition-colors">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Depth gauge */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-end gap-2 mb-2">
          <span className="text-3xl font-mono font-bold" style={{ color: depthColor }}>
            {props.predicted_depth_cm.toFixed(1)}
          </span>
          <span className="text-sm text-muted mb-1">cm depth</span>
        </div>
        {/* Depth bar */}
        <div className="h-2 bg-surface-elevated rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${Math.min(100, (props.predicted_depth_cm / 40) * 100)}%`,
              background: depthColor,
              boxShadow: `0 0 8px ${depthColor}60`,
            }}
          />
        </div>
        <div className="flex justify-between text-[9px] text-muted/60 mt-0.5">
          <span>0</span><span>15cm</span><span>30cm</span><span>40+</span>
        </div>
      </div>

      {/* Stats */}
      <div className="px-4 pb-3">
        <StatRow label="Rainfall" value={props.rainfall_mm_hr.toFixed(1)} unit="mm/hr" />
        <StatRow
          label="ETA to flood"
          value={props.eta_minutes <= 0 ? 'Now' : `${props.eta_minutes.toFixed(0)}`}
          unit={props.eta_minutes > 0 ? 'min' : undefined}
        />
        <StatRow label="Drain clogging" value={`${(props.clogging_idx * 100).toFixed(0)}%`} />
        {!isHover && (
          <StatRow label="Confidence" value={`${(props.confidence * 100).toFixed(0)}%`} />
        )}
        {node && <StatRow label="Elevation" value={node.elevation_m.toFixed(1)} unit="m" />}
      </div>

      {/* ETA warning */}
      {props.eta_minutes > 0 && props.eta_minutes < 30 && (
        <div className="mx-4 mb-3 flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
          <span className="text-xs text-amber-300">
            Flooding expected in ~{Math.ceil(props.eta_minutes)} min
          </span>
        </div>
      )}
    </div>
  );
}
