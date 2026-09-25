'use client';

import { useState, useEffect } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';
import { useFloodStream } from '@/hooks/useFloodStream';
import { useSimulation } from '@/hooks/useSimulation';
import { api } from '@/lib/api';
import type { IntensityPoint, FloodState } from '@/types/flood';
import { Waves, Map, Navigation, BarChart2, TrendingUp, Droplets, AlertTriangle, Activity } from 'lucide-react';
import Link from 'next/link';

export default function AnalyticsPage() {
  const { state: liveState, connected } = useFloodStream();
  const { status, activeScenario } = useSimulation();
  const [history, setHistory] = useState<FloodState[]>([]);

  // Collect history from WebSocket updates
  useEffect(() => {
    if (liveState) {
      setHistory((prev) => {
        const updated = [...prev, liveState];
        return updated.slice(-37); // keep 180 min @ 5 min intervals
      });
    }
  }, [liveState]);

  const intensityData: IntensityPoint[] = status?.intensity_timeseries ?? [];

  // Build risk distribution over time
  const riskTimeline = history.map((s) => ({
    t: Math.round(s.t_minutes),
    severe:     s.summary.severe_count,
    disruptive: s.summary.disruptive_count,
    nuisance:   s.summary.nuisance_count,
    dry:        s.summary.dry_count,
  }));

  const depthTimeline = history.map((s) => ({
    t: Math.round(s.t_minutes),
    max_depth: s.summary.max_depth_cm,
    mean_depth: s.summary.mean_depth_cm,
    drain_util: s.summary.drainage_util_pct,
  }));

  const current = liveState?.summary;

  return (
    <div className="h-screen flex flex-col bg-navy overflow-hidden">
      {/* Top Bar */}
      <header className="top-bar">
        <div className="flex items-center gap-2 flex-shrink-0">
          <Waves className="w-5 h-5 text-accent" />
          <span className="font-bold text-base tracking-tight">UrbanFlow</span>
        </div>
        <div className="w-px h-5 bg-surface-border mx-1" />
        <BarChart2 className="w-4 h-4 text-accent" />
        <span className="text-sm font-semibold text-white">Analytics</span>
        <span className={`ml-2 flex items-center gap-1 text-xs ${connected ? 'text-green-400' : 'text-muted'}`}>
          <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green-400 animate-pulse' : 'bg-muted'}`} />
          {connected ? 'Live' : 'Offline'}
        </span>
        <div className="flex-1" />
        <nav className="flex items-center gap-1">
          <Link href="/" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg hover:bg-surface-card text-xs font-medium text-muted hover:text-white transition-colors">
            <Map className="w-3.5 h-3.5" />Dashboard
          </Link>
          <Link href="/route-planner" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg hover:bg-surface-card text-xs font-medium text-muted hover:text-white transition-colors">
            <Navigation className="w-3.5 h-3.5" />Route Planner
          </Link>
          <Link href="/analytics" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/20 text-xs font-medium text-accent">
            <BarChart2 className="w-3.5 h-3.5" />Analytics
          </Link>
        </nav>
      </header>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Severe Nodes',    value: current?.severe_count ?? 0,        icon: <AlertTriangle className="w-4 h-4" />, color: '#ef4444' },
            { label: 'Max Depth',       value: `${(current?.max_depth_cm ?? 0).toFixed(1)}cm`, icon: <Droplets className="w-4 h-4" />, color: '#f59e0b' },
            { label: 'Drain Util.',     value: `${(current?.drainage_util_pct ?? 0).toFixed(0)}%`, icon: <Activity className="w-4 h-4" />, color: '#3b82f6' },
            { label: 'At-Risk Nodes',   value: (current?.severe_count ?? 0) + (current?.disruptive_count ?? 0), icon: <TrendingUp className="w-4 h-4" />, color: '#f97316' },
          ].map(({ label, value, icon, color }) => (
            <div key={label} className="glass-card p-4">
              <div className="flex items-center gap-2 mb-2" style={{ color }}>
                {icon}
                <span className="text-xs text-muted">{label}</span>
              </div>
              <div className="text-2xl font-mono font-bold text-white">{value}</div>
            </div>
          ))}
        </div>

        {/* Rainfall intensity chart */}
        <div className="glass-card p-4">
          <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <Droplets className="w-4 h-4 text-blue-400" />
            Rainfall Intensity Forecast (0–180 min)
          </h2>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={intensityData}>
                <defs>
                  <linearGradient id="rainGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="rainMaxGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a3a58" />
                <XAxis dataKey="t_minutes" stroke="#64748b" tick={{ fontSize: 10 }}
                       tickFormatter={(v) => `+${v}m`} />
                <YAxis stroke="#64748b" tick={{ fontSize: 10 }} unit=" mm/h" width={60} />
                <Tooltip
                  contentStyle={{ background: '#1a2236', border: '1px solid #2a3a58', borderRadius: 8, fontSize: 11 }}
                  labelFormatter={(v) => `T+${v} min`}
                />
                <Area type="monotone" dataKey="mean_mm_hr" name="Mean (mm/hr)"
                      stroke="#3b82f6" fill="url(#rainGrad)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="max_mm_hr" name="Peak (mm/hr)"
                      stroke="#ef4444" fill="url(#rainMaxGrad)" strokeWidth={1.5} dot={false} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* At-risk nodes over time */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="glass-card p-4">
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-orange-400" />
              Risk Distribution Over Time
            </h2>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={riskTimeline} stackOffset="expand">
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a3a58" />
                  <XAxis dataKey="t" stroke="#64748b" tick={{ fontSize: 10 }} tickFormatter={(v) => `+${v}m`} />
                  <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#1a2236', border: '1px solid #2a3a58', borderRadius: 8, fontSize: 11 }}
                    labelFormatter={(v) => `T+${v} min`}
                  />
                  <Bar dataKey="severe"     name="Severe"     stackId="a" fill="#ef4444" />
                  <Bar dataKey="disruptive" name="Disruptive" stackId="a" fill="#f97316" />
                  <Bar dataKey="nuisance"   name="Nuisance"   stackId="a" fill="#f59e0b" />
                  <Bar dataKey="dry"        name="Dry"        stackId="a" fill="#374151" />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card p-4">
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              Max Depth & Drain Utilisation
            </h2>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={depthTimeline}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a3a58" />
                  <XAxis dataKey="t" stroke="#64748b" tick={{ fontSize: 10 }} tickFormatter={(v) => `+${v}m`} />
                  <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#1a2236', border: '1px solid #2a3a58', borderRadius: 8, fontSize: 11 }}
                    labelFormatter={(v) => `T+${v} min`}
                  />
                  <Area type="monotone" dataKey="max_depth" name="Max depth (cm)" stroke="#ef4444" fill="none" strokeWidth={2} dot={false} />
                  <Area type="monotone" dataKey="drain_util" name="Drain util. (%)" stroke="#3b82f6" fill="none" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <p className="text-xs text-muted/40 text-center pb-2">
          UrbanFlow | Nexora | SIH 2026 | PS ID 26085 | Demo: Chennai T. Nagar ({activeScenario})
        </p>
      </div>
    </div>
  );
}
