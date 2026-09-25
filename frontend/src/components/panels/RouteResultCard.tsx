'use client';

import type { RouteResult } from '@/types/flood';
import { RISK_COLORS } from '@/lib/mapStyles';
import { formatDuration, formatDistance } from '@/lib/mapStyles';
import { X, Navigation, Shield, AlertTriangle, Clock, TrendingDown } from 'lucide-react';

interface RouteResultCardProps {
  result: RouteResult;
  onClear: () => void;
}

export default function RouteResultCard({ result, onClear }: RouteResultCardProps) {
  const { comparison, safe_route, naive_route } = result;
  const distanceSavedPositive = comparison.distance_saved_m > 0;
  const anyFlooded = comparison.max_depth_avoided_cm > 0;

  return (
    <div className="w-80 bg-surface-card/95 backdrop-blur-sm rounded-xl border border-surface-border shadow-2xl animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-green-400" />
          <span className="text-sm font-semibold text-white">Route Comparison</span>
        </div>
        <button
          id="clear-route-btn"
          onClick={onClear}
          className="text-muted hover:text-white transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Route cards */}
      <div className="p-4 space-y-3">
        {/* Safe route */}
        <div className="bg-green-500/5 border border-green-500/20 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-3 h-0.5 bg-green-400 rounded-full" />
            <span className="text-xs font-semibold text-green-400">Flood-Safe Route</span>
          </div>
          <div className="flex gap-4">
            <div>
              <div className="text-lg font-mono font-bold text-white">
                {safe_route.max_depth_cm.toFixed(1)} cm
              </div>
              <div className="text-[10px] text-muted">max depth</div>
            </div>
            <div>
              <div className="text-lg font-mono font-bold text-white">
                {formatDistance(safe_route.distance_m)}
              </div>
              <div className="text-[10px] text-muted">distance</div>
            </div>
          </div>
        </div>

        {/* Naive route */}
        <div className="bg-surface-elevated/50 border border-surface-border rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-3 h-0.5 bg-slate-400 rounded-full border-dashed" style={{ borderTop: '2px dashed #94a3b8', background: 'none' }} />
            <span className="text-xs font-semibold text-muted">Naive Shortest Route</span>
          </div>
          <div className="flex gap-4">
            <div>
              <div className="text-lg font-mono font-bold text-muted">
                {naive_route.max_depth_cm.toFixed(1)} cm
              </div>
              <div className="text-[10px] text-muted">max depth</div>
            </div>
            <div>
              <div className="text-lg font-mono font-bold text-muted">
                {formatDistance(naive_route.distance_m)}
              </div>
              <div className="text-[10px] text-muted">distance</div>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-2">
          <div className={`flex flex-col items-center p-2 rounded-lg border bg-surface-elevated border-surface-border`}>
            <Clock className={`w-3.5 h-3.5 mb-1 ${!distanceSavedPositive ? 'text-red-400' : 'text-muted'}`} />
            <span className={`text-sm font-mono font-bold ${!distanceSavedPositive ? 'text-red-400' : 'text-white'}`}>
              {distanceSavedPositive ? `-${formatDistance(comparison.distance_saved_m)}` : `+${formatDistance(Math.abs(comparison.distance_saved_m))}`}
            </span>
            <span className="text-[9px] text-muted text-center">detour distance</span>
          </div>

          <div className={`flex flex-col items-center p-2 rounded-lg border ${
            anyFlooded ? 'bg-red-500/10 border-red-500/20' : 'bg-surface-elevated border-surface-border'
          }`}>
            <AlertTriangle className={`w-3.5 h-3.5 mb-1 ${anyFlooded ? 'text-red-400' : 'text-muted'}`} />
            <span className={`text-sm font-mono font-bold ${anyFlooded ? 'text-red-400' : 'text-white'}`}>
              {comparison.max_depth_avoided_cm.toFixed(1)} cm
            </span>
            <span className="text-[9px] text-muted text-center">depth avoided</span>
          </div>

          <div className="flex flex-col items-center p-2 rounded-lg border bg-surface-elevated border-surface-border">
            <TrendingDown className="w-3.5 h-3.5 mb-1 text-orange-400" />
            <span className="text-sm font-mono font-bold text-white">
              {comparison.safe_weight_ratio.toFixed(2)}x
            </span>
            <span className="text-[9px] text-muted text-center">safety ratio</span>
          </div>
        </div>

        {anyFlooded && (
          <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
            <Shield className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-300">
              Safe route avoids deep waters (up to {comparison.max_depth_avoided_cm.toFixed(1)} cm avoided).
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
