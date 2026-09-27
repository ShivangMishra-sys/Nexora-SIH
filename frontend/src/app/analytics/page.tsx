'use client';

import { useState, useEffect } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';
import { useFloodStream } from '@/hooks/useFloodStream';
import { useSimulation } from '@/hooks/useSimulation';
import type { IntensityPoint, FloodState } from '@/types/flood';
import { Waves, Map, Navigation, BarChart2, TrendingUp, Droplets, AlertTriangle, Activity, Zap } from 'lucide-react';
import Link from 'next/link';

const TOOLTIP_STYLE = {
  background: 'rgba(8,13,26,0.98)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 10,
  fontSize: 11,
  color: '#f1f5f9',
  boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
};

const AXIS_STYLE = { fill: 'rgba(255,255,255,0.35)', fontSize: 10 };
const GRID_STYLE = { stroke: 'rgba(255,255,255,0.05)', strokeDasharray: '3 3' };

import { api } from '@/lib/api';

export default function AnalyticsPage() {
  const { state: liveState, connected } = useFloodStream();
  const { status, activeScenario } = useSimulation();
  const [history, setHistory] = useState<FloodState[]>([]);
  const [initialFlood, setInitialFlood] = useState<any>(null);
  const [validation, setValidation] = useState<{ rmse_cm?: number; f1_flood_detection?: number } | null>(null);

  useEffect(() => {
    api.getFloodState().then(s => {
      if (s) {
        setInitialFlood(s);
        setHistory(prev => prev.length === 0 ? [s] : prev);
        if (s.validation) setValidation(s.validation);
      }
    }).catch(console.error);
    api.getValidation().then(v => {
      if (v) setValidation(v);
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (liveState) {
      setHistory(prev => [...prev, liveState].slice(-37));
      if ((liveState as any).validation) {
        setValidation((liveState as any).validation);
      }
    }
  }, [liveState]);

  const intensityData: IntensityPoint[] = status?.intensity_timeseries ?? [];

  const riskTimeline = history.map(s => {
    const sum = (s as any).summary ?? s;
    return {
      t: Math.round(s.t_minutes ?? 0),
      severe:     sum.severe_count ?? 0,
      disruptive: sum.disruptive_count ?? 0,
      nuisance:   sum.nuisance_count ?? 0,
      dry:        sum.dry_count ?? 0,
    };
  });

  const depthTimeline = history.map(s => {
    const sum = (s as any).summary ?? s;
    return {
      t: Math.round(s.t_minutes ?? 0),
      max_depth:  sum.max_depth_cm ?? 0,
      mean_depth: sum.mean_depth_cm ?? 0,
      drain_util: sum.drainage_util_pct ?? 0,
    };
  });

  const current: any = liveState?.summary ?? liveState ?? initialFlood?.summary ?? initialFlood;

  const kpis = [
    {
      label: 'Max Depth',
      value: (current?.max_depth_cm ?? 0).toFixed(1),
      unit: 'cm',
      icon: <Droplets size={16} />,
      color: '#f59e0b',
      bg: 'rgba(245,158,11,0.08)',
      border: 'rgba(245,158,11,0.2)',
      change: history.length > 1 ? (current?.max_depth_cm ?? 0) - ((history[history.length - 2]?.summary ?? history[history.length - 2] as any)?.max_depth_cm ?? 0) : 0,
    },
    {
      label: 'Mean Depth',
      value: (current?.mean_depth_cm ?? 0).toFixed(1),
      unit: 'cm',
      icon: <Waves size={16} />,
      color: '#38bdf8',
      bg: 'rgba(56,189,248,0.08)',
      border: 'rgba(56,189,248,0.2)',
      change: history.length > 1 ? (current?.mean_depth_cm ?? 0) - ((history[history.length - 2]?.summary ?? history[history.length - 2] as any)?.mean_depth_cm ?? 0) : 0,
    },
    {
      label: 'Severe Nodes',
      value: current?.severe_count ?? 0,
      unit: '',
      icon: <AlertTriangle size={16} />,
      color: '#ef4444',
      bg: 'rgba(239,68,68,0.08)',
      border: 'rgba(239,68,68,0.2)',
      change: history.length > 1 ? (current?.severe_count ?? 0) - ((history[history.length - 2]?.summary ?? history[history.length - 2] as any)?.severe_count ?? 0) : 0,
    },
    {
      label: 'RMSE Error',
      value: validation?.rmse_cm !== undefined ? validation.rmse_cm.toFixed(1) : '—',
      unit: 'cm',
      icon: <TrendingUp size={16} />,
      color: '#fbbf24',
      bg: 'rgba(251,191,36,0.08)',
      border: 'rgba(251,191,36,0.2)',
      change: 0,
    },
    {
      label: 'F1 Score',
      value: validation?.f1_flood_detection !== undefined ? ((validation.f1_flood_detection) * 100).toFixed(0) : '—',
      unit: '%',
      icon: <TrendingUp size={16} />,
      color: '#22c55e',
      bg: 'rgba(34,197,94,0.08)',
      border: 'rgba(34,197,94,0.2)',
      change: 0,
    },
    {
      label: 'Drain Util.',
      value: (current?.drainage_util_pct ?? 0).toFixed(0),
      unit: '%',
      icon: <Activity size={16} />,
      color: '#3b82f6',
      bg: 'rgba(59,130,246,0.08)',
      border: 'rgba(59,130,246,0.2)',
      change: history.length > 1 ? (current?.drainage_util_pct ?? 0) - ((history[history.length - 2]?.summary ?? history[history.length - 2] as any)?.drainage_util_pct ?? 0) : 0,
    },
  ];

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--navy)', color: 'var(--text)', overflow: 'hidden', fontFamily: '"Inter", system-ui, sans-serif' }}>

      {/* Top Bar */}
      <header className="top-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 12px rgba(59,130,246,0.4)',
          }}>
            <Waves size={15} color="#fff" />
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.2 }}>UrbanFlow</div>
            <div style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Anna Nagar · SIH 2026</div>
          </div>
        </div>

        <div className="divider" />

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <BarChart2 size={14} color="#3b82f6" />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Analytics</span>
        </div>

        <div className={`status-badge ${connected ? 'live' : 'offline'}`}>
          <div className={`status-dot ${connected ? 'animate-pulse' : ''}`} />
          {connected ? 'Live' : 'Offline'}
        </div>

        {/* Scenario pill */}
        {activeScenario && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px',
            borderRadius: 8, background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.25)',
            fontSize: 11, color: '#a5b4fc',
          }}>
            <Zap size={10} />
            {activeScenario.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </div>
        )}

        <div style={{ flex: 1 }} />

        <nav style={{ display: 'flex', gap: 2 }}>
          <Link href="/" className="nav-link"><Map size={13} />Dashboard</Link>
          <Link href="/route-planner" className="nav-link"><Navigation size={13} />Route Planner</Link>
          <Link href="/analytics" className="nav-link active"><BarChart2 size={13} />Analytics</Link>
        </nav>
      </header>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>

        {/* KPI Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12 }}>
          {kpis.map(({ label, value, unit, icon, color, bg, border, change }) => (
            <div key={label} style={{
              background: bg, border: `1px solid ${border}`,
              borderRadius: 16, padding: '16px 18px',
              transition: 'all 0.2s ease', position: 'relative', overflow: 'hidden',
            }}>
              {/* Glow backdrop */}
              <div style={{
                position: 'absolute', top: -20, right: -20, width: 80, height: 80,
                borderRadius: '50%', background: color, opacity: 0.06, filter: 'blur(20px)',
                pointerEvents: 'none',
              }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, color }}>
                {icon}
                <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', fontWeight: 500 }}>{label}</span>
              </div>
              <div style={{ fontSize: 30, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color, lineHeight: 1, marginBottom: 4 }}>
                {value}<span style={{ fontSize: 14, fontWeight: 500, marginLeft: 2 }}>{unit}</span>
              </div>
              {change !== 0 && (
                <div style={{ fontSize: 10, color: change > 0 ? '#f87171' : '#4ade80' }}>
                  {change > 0 ? '▲' : '▼'} {Math.abs(typeof change === 'number' ? change : parseFloat(String(change))).toFixed(1)} from last tick
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Rainfall Intensity Chart */}
        <div style={{
          background: 'var(--surface-card)', border: '1px solid var(--surface-border)',
          borderRadius: 16, padding: 20,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: 'rgba(59,130,246,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Droplets size={16} color="#60a5fa" />
              </div>
              <div>
                <h2 style={{ fontSize: 13, fontWeight: 700, color: '#fff', margin: 0 }}>Rainfall Intensity Forecast</h2>
                <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', margin: 0 }}>0–180 min nowcast (PySTEPS)</p>
              </div>
            </div>
            {intensityData.length === 0 && (
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>Awaiting simulation data…</div>
            )}
          </div>
          <div style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={intensityData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="rainGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="rainMaxGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid {...GRID_STYLE} />
                <XAxis dataKey="t_minutes" tick={AXIS_STYLE} tickLine={false} axisLine={false} tickFormatter={v => `+${v}m`} />
                <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} unit=" mm/h" width={56} />
                <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={v => `T+${v} min`} cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }} />
                <Area type="monotone" dataKey="mean_mm_hr" name="Mean (mm/hr)" stroke="#3b82f6" fill="url(#rainGrad)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="max_mm_hr"  name="Peak (mm/hr)" stroke="#ef4444" fill="url(#rainMaxGrad)" strokeWidth={1.5} dot={false} />
                <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', paddingTop: 8 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Two-column charts */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

          {/* Risk Distribution */}
          <div style={{
            background: 'var(--surface-card)', border: '1px solid var(--surface-border)',
            borderRadius: 16, padding: 20,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: 'rgba(249,115,22,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <AlertTriangle size={16} color="#fb923c" />
              </div>
              <div>
                <h2 style={{ fontSize: 13, fontWeight: 700, color: '#fff', margin: 0 }}>Risk Distribution</h2>
                <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', margin: 0 }}>Node count by severity over time</p>
              </div>
            </div>
            <div style={{ height: 180 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={riskTimeline} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="t" tick={AXIS_STYLE} tickLine={false} axisLine={false} tickFormatter={v => `+${v}m`} />
                  <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={v => `T+${v} min`} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                  <Bar dataKey="severe"     name="Severe"     stackId="a" fill="#ef4444" radius={[0,0,0,0]} />
                  <Bar dataKey="disruptive" name="Disruptive" stackId="a" fill="#f97316" />
                  <Bar dataKey="nuisance"   name="Nuisance"   stackId="a" fill="#f59e0b" />
                  <Bar dataKey="dry"        name="Dry"        stackId="a" fill="rgba(107,114,128,0.5)" radius={[4,4,0,0]} />
                  <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', paddingTop: 8 }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Depth & Drain Utilisation */}
          <div style={{
            background: 'var(--surface-card)', border: '1px solid var(--surface-border)',
            borderRadius: 16, padding: 20,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: 'rgba(59,130,246,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Activity size={16} color="#60a5fa" />
              </div>
              <div>
                <h2 style={{ fontSize: 13, fontWeight: 700, color: '#fff', margin: 0 }}>Depth & Drain Utilisation</h2>
                <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', margin: 0 }}>cm & % over simulation time</p>
              </div>
            </div>
            <div style={{ height: 180 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={depthTimeline} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="depthGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="drainGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="t" tick={AXIS_STYLE} tickLine={false} axisLine={false} tickFormatter={v => `+${v}m`} />
                  <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={v => `T+${v} min`} cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }} />
                  <Area type="monotone" dataKey="max_depth"  name="Max depth (cm)"  stroke="#ef4444" fill="url(#depthGrad)" strokeWidth={2} dot={false} />
                  <Area type="monotone" dataKey="drain_util" name="Drain util. (%)" stroke="#3b82f6" fill="url(#drainGrad)" strokeWidth={1.5} dot={false} strokeDasharray="5 3" />
                  <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', paddingTop: 8 }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ textAlign: 'center', fontSize: 10, color: 'rgba(255,255,255,0.15)', paddingBottom: 8 }}>
          UrbanFlow v2 · Team Nexora · SIH 2026 · PS ID 26085 · Anna Nagar, Chennai ·{' '}
          <span style={{ color: 'rgba(255,255,255,0.25)', fontFamily: 'JetBrains Mono, monospace' }}>{activeScenario}</span>
        </div>
      </div>
    </div>
  );
}
