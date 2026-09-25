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
  const timeSavedPositive = comparison.time_saved_s > 0;
  const anyFlooded = comparison.flooded_edges_avoided > 0;

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
                {formatDuration(safe_route.travel_time_s)}
              </div>
              <div className="text-[10px] text-muted">travel time</div>
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
                {formatDuration(naive_route.travel_time_s)}
              </div>
              <div className="text-[10px] text-muted">travel time</div>
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
          <div className={`flex flex-col items-center p-2 rounded-lg border ${
            timeSavedPositive ? 'bg-green-500/10 border-green-500/20' : 'bg-surface-elevated border-surface-border'
          }`}>
            <Clock className={`w-3.5 h-3.5 mb-1 ${timeSavedPositive ? 'text-green-400' : 'text-muted'}`} />
            <span className={`text-sm font-mono font-bold ${timeSavedPositive ? 'text-green-400' : 'text-white'}`}>
              {timeSavedPositive ? `-${formatDuration(comparison.time_saved_s)}` : '—'}
            </span>
            <span className="text-[9px] text-muted text-center">time saved</span>
          </div>

          <div className={`flex flex-col items-center p-2 rounded-lg border ${
            anyFlooded ? 'bg-red-500/10 border-red-500/20' : 'bg-surface-elevated border-surface-border'
          }`}>
            <AlertTriangle className={`w-3.5 h-3.5 mb-1 ${anyFlooded ? 'text-red-400' : 'text-muted'}`} />
            <span className={`text-sm font-mono font-bold ${anyFlooded ? 'text-red-400' : 'text-white'}`}>
              {comparison.flooded_edges_avoided}
            </span>
            <span className="text-[9px] text-muted text-center">floods avoided</span>
          </div>

          <div className="flex flex-col items-center p-2 rounded-lg border bg-surface-elevated border-surface-border">
            <TrendingDown className="w-3.5 h-3.5 mb-1 text-orange-400" />
            <span className="text-sm font-mono font-bold text-white">
              {comparison.severe_edges_avoided}
            </span>
            <span className="text-[9px] text-muted text-center">severe zones</span>
          </div>
        </div>

        {anyFlooded && (
          <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
            <Shield className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-300">
              Safe route avoids {comparison.severe_edges_avoided} severe and {comparison.disruptive_edges_avoided} disruptive flood zones.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
