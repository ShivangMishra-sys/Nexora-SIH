'use client';

import { useEffect, useRef, useState } from 'react';
import type { FloodNode } from '@/types/flood';
import { RISK_COLORS } from '@/lib/mapStyles';
import { api } from '@/lib/api';
import { AlertTriangle, Zap } from 'lucide-react';

export default function IncidentFeed() {
  const [incidents, setIncidents] = useState<FloodNode[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await api.getIncidentFeed(15);
        setIncidents(data);
        // Auto-scroll to top when new data arrives
        if (scrollRef.current) {
          scrollRef.current.scrollTo({ top: 0, behavior: 'smooth' });
        }
      } catch {
        // ignore
      }
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, []);

  if (incidents.length === 0) return null;

  return (
    <div className="w-64 bg-surface-card/90 backdrop-blur-sm rounded-xl border border-surface-border shadow-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-surface-border bg-surface-elevated/50">
        <Zap className="w-3.5 h-3.5 text-red-400 animate-pulse" />
        <span className="text-xs font-semibold text-white">Incident Feed</span>
        <span className="ml-auto text-xs font-mono text-red-400 bg-red-500/10 px-1.5 rounded">
          {incidents.length}
        </span>
      </div>

      {/* Scrollable list */}
      <div
        ref={scrollRef}
        className="max-h-48 overflow-y-auto scrollbar-thin scrollbar-track-surface-card scrollbar-thumb-surface-border"
      >
        {incidents.map((node, idx) => {
          const color = RISK_COLORS[node.risk_level as keyof typeof RISK_COLORS] ?? '#64748b';
          return (
            <div
              key={node.node_id}
              className="flex items-center gap-2 px-3 py-2 border-b border-surface-border/30 hover:bg-surface-elevated/40 transition-colors"
              style={{ animationDelay: `${idx * 50}ms` }}
            >
              <div
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: color, boxShadow: `0 0 5px ${color}` }}
              />
              <div className="flex-1 min-w-0">
                <div className="text-xs text-white font-mono truncate">
                  {node.predicted_depth_cm.toFixed(1)}cm
                  <span className="text-muted ml-1 font-sans normal-case">
                    {node.risk_level}
                  </span>
                </div>
                <div className="text-[10px] text-muted">
                  {node.lat.toFixed(4)}, {node.lon.toFixed(4)}
                </div>
              </div>
              {node.risk_level === 'severe' && (
                <AlertTriangle className="w-3 h-3 text-red-400 flex-shrink-0" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
