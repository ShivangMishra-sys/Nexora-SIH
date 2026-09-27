'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import {
  Waves, Navigation, BarChart2, Map, Play, Pause,
  AlertTriangle, Activity, RefreshCw,
  Wind, Droplets, Search, Bell, X, MousePointer2,
  Shield, Zap, TrendingUp, ChevronRight,
} from 'lucide-react';
import { api, createFloodWebSocket } from '@/lib/api';
import type {
  FloodSummary, NowcastAPI,
  WSFloodMessage,
} from '@/lib/api';
import type { RouteResult, GeoJSONFeatureCollection } from '@/types/flood';
import type { RouteSelectionState } from '@/types/flood';

const FloodMap = dynamic(() => import('@/components/map/FloodMap'), { ssr: false });

// ── Constants ──────────────────────────────────────────────────────────────
const RISK_COLORS = {
  safe:       '#6b7280',
  caution:    '#f59e0b',
  critical:   '#f97316',
  impassable: '#ef4444',
};

const SCENARIOS = [
  { id: 'cloudburst_extreme', label: 'Cloudburst', sublabel: 'Extreme', dbz: 55, icon: '⛈️', color: '#ef4444' },
  { id: 'monsoon_front',      label: 'Monsoon',    sublabel: 'Front',   dbz: 45, icon: '🌧️', color: '#f97316' },
  { id: 'moderate_steady',    label: 'Moderate',   sublabel: 'Steady',  dbz: 38, icon: '🌦️', color: '#f59e0b' },
  { id: 'light_drizzle',      label: 'Light',      sublabel: 'Drizzle', dbz: 25, icon: '🌂', color: '#3b82f6' },
];

// ── Main Dashboard ────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [floodState, setFloodState]         = useState<any>(null);
  const [summary, setSummary]               = useState<FloodSummary | null>(null);
  const [network, setNetwork]               = useState<GeoJSONFeatureCollection | null>(null);
  const [nowcast, setNowcast]               = useState<NowcastAPI | null>(null);
  const [connected, setConnected]           = useState(false);
  const [activeScenario, setActiveScenario] = useState('cloudburst_extreme');
  const [isPlaying, setIsPlaying]           = useState(true);
  const [timelineT, setTimelineT]           = useState(0);
  const [isScrubbing, setIsScrubbing]       = useState(false);
  const [snapshots, setSnapshots]           = useState<number[]>([]);
  const [validation, setValidation]         = useState<{ rmse_cm?: number; f1_flood_detection?: number } | null>(null);
  const [geocodeQ, setGeocodeQ]             = useState('');
  const [geocodeResult, setGeocodeResult]   = useState<{ lat: number; lon: number; address: string } | null>(null);
  const [blockagePct, setBlockagePct]       = useState(0);
  const [retraining, setRetraining]         = useState(false);
  const [alerts, setAlerts]                 = useState<string[]>([]);
  const [showPanel, setShowPanel]           = useState(true);

  // Route state
  const [routeState, setRouteState]   = useState<RouteSelectionState>({ step: 'idle' });
  const [routeResult, setRouteResult] = useState<RouteResult | null>(null);
  const [vehicleClass, setVehicleClass] = useState('car');
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  // ── Load initial data on mount ──────────────────────────────────────────
  useEffect(() => {
    api.getNetworkGraph().then(setNetwork).catch(console.error);
    api.listSnapshots().then(s => setSnapshots(s.available_minutes)).catch(console.error);
    api.getValidation().then(setValidation).catch(console.error);
    api.getNowcast().then(setNowcast).catch(console.error);
    api.getFloodState().then((s: any) => {
      if (s) {
        setFloodState(s);
        if (s.t_minutes !== undefined) setTimelineT(s.t_minutes);
        if (s.validation) setValidation(s.validation);
      }
    }).catch(console.error);
    api.getFloodSummary().then((s: any) => {
      if (s && s.status !== 'no_data') setSummary(s);
    }).catch(console.error);
  }, []);

  const isScrubbingRef = useRef(isScrubbing);
  useEffect(() => {
    isScrubbingRef.current = isScrubbing;
  }, [isScrubbing]);

  // ── WebSocket flood stream ─────────────────────────────────────────────
  useEffect(() => {
    const connect = () => {
      const ws = createFloodWebSocket(
        (msg: WSFloodMessage) => {
          if (!isScrubbingRef.current && msg.t_minutes !== undefined) {
            setTimelineT(msg.t_minutes);
          }
          if ((msg as any).validation) setValidation((msg as any).validation);
          if ((msg as any).summary) setSummary((msg as any).summary);

          api.getFloodState().then((s: any) => {
            setFloodState(s);
            if (s.validation) setValidation(s.validation);
          }).catch(console.error);
          api.getFloodSummary().then((s: any) => setSummary(s)).catch(console.error);
          api.getNetworkGraph().then(setNetwork).catch(console.error);
          api.getNowcast().then(setNowcast).catch(console.error);
        },
        () => setConnected(true),
      );
      ws.onopen  = () => setConnected(true);
      ws.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
      wsRef.current = ws;
    };
    connect();
    return () => wsRef.current?.close();
  }, []);

  const togglePlay = useCallback(async () => {
    try {
      if (isPlaying) {
        await api.pause();
        setIsPlaying(false);
        addAlert('Simulation paused');
      } else {
        if (timelineT >= 180) {
          const sc = SCENARIOS.find(s => s.id === activeScenario);
          await api.runScenario({
            scenario: activeScenario,
            intensity_dbz: sc?.dbz ?? 50,
            storm_center: [0.45, 0.55],
            radius_fraction: 0.25,
            drain_blockage_pct: blockagePct,
          });
          setTimelineT(0);
          addAlert('Simulation restarted from T+0m');
        } else {
          await api.resume();
          addAlert('Simulation resumed');
        }
        setIsPlaying(true);
      }
    } catch (e) {
      console.error(e);
    }
  }, [isPlaying, timelineT, activeScenario, blockagePct]);

  // ── Scenario controls ──────────────────────────────────────────────────
  const handleScenario = useCallback(async (id: string, dbz: number) => {
    setActiveScenario(id);
    setTimelineT(0);
    setIsPlaying(true);
    setIsScrubbing(false);

    const sc = SCENARIOS.find(s => s.id === id);
    addAlert(`Scenario: ${sc?.label ?? id} (${dbz} dBZ) — simulation started`);

    try {
      const res = await api.runScenario({
        scenario: id,
        intensity_dbz: dbz,
        storm_center: [0.45, 0.55],
        radius_fraction: 0.25,
        drain_blockage_pct: blockagePct,
      });

      if ((res as any)?.state) {
        setFloodState((res as any).state);
      }

      const [freshState, freshSummary, freshNowcast] = await Promise.all([
        api.getFloodState(0).catch(() => null),
        api.getFloodSummary().catch(() => null),
        api.getNowcast().catch(() => null),
      ]);
      if (freshState) setFloodState(freshState);
      if (freshSummary && freshSummary.status !== 'no_data') setSummary(freshSummary);
      if (freshNowcast) setNowcast(freshNowcast);
    } catch (err) {
      console.error('Failed to run scenario:', err);
      addAlert('Failed to switch scenario');
    }
  }, [blockagePct]);

  const handleBlockageApply = useCallback(async () => {
    const sc = SCENARIOS.find(s => s.id === activeScenario)!;
    setTimelineT(0);
    setIsPlaying(true);
    setIsScrubbing(false);
    await api.runScenario({
      scenario: activeScenario,
      intensity_dbz: sc.dbz,
      storm_center: [0.45, 0.55],
      radius_fraction: 0.25,
      drain_blockage_pct: blockagePct,
    });
    addAlert(`Drain blockage what-if: ${blockagePct}% — simulation reset`);
  }, [activeScenario, blockagePct]);

  const handleRetrain = useCallback(async () => {
    setRetraining(true);
    await api.retrainBlockage();
    setRetraining(false);
    addAlert('Blockage model retrained successfully');
  }, []);

  // ── Timeline scrub ─────────────────────────────────────────────────────
  const handleSeek = useCallback(async (t: number) => {
    setTimelineT(t);
    setIsScrubbing(true);
    const snap = await api.getFloodState(t).catch(() => null);
    if (snap) {
      setFloodState(snap);
      if (snap.summary) setSummary(snap.summary);
    }
    setTimeout(() => setIsScrubbing(false), 3000);
  }, []);

  // ── Route selection ────────────────────────────────────────────────────
  const handleMapClick = useCallback(async (lat: number, lon: number) => {
    if (routeState.step === 'selecting_start') {
      setRouteState({ step: 'selecting_end', start: { lat, lon } });
    } else if (routeState.step === 'selecting_end') {
      const { start } = routeState;
      setRouteState({ step: 'computing', start, end: { lat, lon } });
      try {
        const result = await api.computeRoute([start.lat, start.lon], [lat, lon], vehicleClass);
        setRouteResult(result);
        setRouteState({ step: 'done', start, end: { lat, lon }, result });
        addAlert(`Route: ${(result.safe_route.distance_m / 1000).toFixed(1)} km safe path found`);
      } catch {
        setRouteState({ step: 'idle' });
        addAlert('Route computation failed — no path found');
      }
    }
  }, [routeState, vehicleClass]);

  const clearRoute = useCallback(() => {
    setRouteState({ step: 'idle' });
    setRouteResult(null);
  }, []);

  // ── Geocode ────────────────────────────────────────────────────────────
  const handleGeocode = useCallback(async () => {
    const result = await api.geocode(geocodeQ).catch(() => null);
    if (result && !('error' in result)) setGeocodeResult(result);
  }, [geocodeQ]);

  const addAlert = (msg: string) => {
    setAlerts(prev => [`${new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })} — ${msg}`, ...prev].slice(0, 8));
  };

  const routeHint =
    routeState.step === 'selecting_start' ? '📍 Click map to set START point' :
    routeState.step === 'selecting_end'   ? '🏁 Click map to set END point'   :
    routeState.step === 'computing'       ? '⏳ Computing flood-safe route…'   : null;

  const activeScenarioData = SCENARIOS.find(s => s.id === activeScenario);

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--navy)', color: 'var(--text)', overflow: 'hidden', fontFamily: '"Inter", system-ui, sans-serif' }}>

      {/* ── Top Bar ───────────────────────────────────────────────────── */}
      <header className="top-bar">
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)',
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

        {/* Live status */}
        <div className={`status-badge ${connected ? 'live' : 'offline'}`}>
          <div className={`status-dot ${connected ? 'animate-pulse' : ''}`} />
          {connected ? 'Live' : 'Offline'}
        </div>

        {/* Scenario pills */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 4 }}>
          {SCENARIOS.map(s => (
            <button
              key={s.id}
              onClick={() => handleScenario(s.id, s.dbz)}
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '5px 10px', borderRadius: 8, border: 'none',
                fontSize: 11, fontWeight: 500, cursor: 'pointer',
                background: activeScenario === s.id ? `${s.color}22` : 'transparent',
                color: activeScenario === s.id ? s.color : 'var(--text-muted)',
                boxShadow: activeScenario === s.id ? `0 0 0 1px ${s.color}44` : 'none',
                transition: 'all 0.15s ease',
              }}
            >
              <span>{s.icon}</span>
              <span>{s.label}</span>
            </button>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        {/* Validation metrics */}
        {validation?.rmse_cm !== undefined && (
          <div style={{ display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-muted)' }}>
            <span>RMSE <span style={{ color: '#f59e0b', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>{validation.rmse_cm.toFixed(1)}cm</span></span>
            <span>F1 <span style={{ color: '#22c55e', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>{((validation.f1_flood_detection ?? 0) * 100).toFixed(0)}%</span></span>
          </div>
        )}

        <div className="divider" />

        {/* Navigation */}
        <nav style={{ display: 'flex', gap: 2 }}>
          <Link href="/" className="nav-link active"><Map size={13} />Dashboard</Link>
          <Link href="/route-planner" className="nav-link"><Navigation size={13} />Route Planner</Link>
          <Link href="/analytics" className="nav-link"><BarChart2 size={13} />Analytics</Link>
        </nav>
      </header>

      {/* ── Main content ──────────────────────────────────────────────── */}
      <main style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>

        {/* Map area */}
        <div style={{ flex: 1, position: 'relative' }}>
          <FloodMap
            networkGeoJSON={network}
            floodState={floodState as any}
            routeResult={routeResult}
            routeState={routeState}
            onMapClick={handleMapClick}
            onNodeHover={setHoveredNodeId}
          />

          {/* Route hint banner */}
          {routeHint && (
            <div style={{
              position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)',
              zIndex: 10, display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 18px', borderRadius: 14,
              background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)',
              backdropFilter: 'blur(16px)', fontSize: 13, fontWeight: 500, color: '#93c5fd',
              boxShadow: '0 4px 24px rgba(59,130,246,0.2)',
            }} className="animate-slide-up">
              <MousePointer2 size={14} style={{ animation: 'pulse 2s infinite' }} />
              {routeHint}
              <button onClick={clearRoute} style={{ marginLeft: 4, background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.4)', padding: 2 }}>
                <X size={13} />
              </button>
            </div>
          )}

          {/* Summary stats bar — top left */}
          {summary && (
            <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10 }} className="animate-fade-in">
              <div style={{
                display: 'flex', gap: 1, padding: '10px 14px',
                background: 'rgba(8,13,26,0.92)', border: '1px solid rgba(255,255,255,0.09)',
                borderRadius: 14, backdropFilter: 'blur(20px)',
                boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
              }}>
                {[
                  { label: 'Max Depth', value: `${summary.max_depth_cm.toFixed(1)}`, unit: 'cm', color: '#f97316' },
                  { label: 'Mean Depth', value: `${((summary as any).mean_depth_cm ?? 0).toFixed(1)}`, unit: 'cm', color: '#38bdf8' },
                  { label: 'Severe Nodes', value: `${(summary as any).severe_count ?? 0}`, unit: '', color: '#ef4444' },
                  { label: 'Impassable', value: `${summary.impassable_pct.toFixed(1)}`, unit: '%', color: '#ef4444' },
                  { label: 'Critical', value: `${summary.critical_pct.toFixed(1)}`, unit: '%', color: '#f97316' },
                  { label: 'Hotspots', value: String(summary.hotspots?.length ?? 0), unit: '', color: '#f59e0b' },
                ].map(({ label, value, unit, color }, i) => (
                  <React.Fragment key={label}>
                    {i > 0 && <div style={{ width: 1, background: 'rgba(255,255,255,0.06)', margin: '0 12px' }} />}
                    <div style={{ textAlign: 'center', padding: '0 4px' }}>
                      <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 18, fontWeight: 700, color, lineHeight: 1 }}>
                        {value}<span style={{ fontSize: 11, marginLeft: 2 }}>{unit}</span>
                      </div>
                      <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginTop: 3, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}

          {/* Risk legend — bottom left */}
          <div style={{ position: 'absolute', bottom: 96, left: 16, zIndex: 10 }}>
            <div style={{
              padding: '10px 14px', borderRadius: 12,
              background: 'rgba(8,13,26,0.92)', border: '1px solid rgba(255,255,255,0.09)',
              backdropFilter: 'blur(20px)',
            }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>Risk Bands</div>
              {[
                { level: 'safe',       label: 'Dry · &lt;5 cm',   color: RISK_COLORS.safe },
                { level: 'caution',    label: 'Caution · 5–15 cm',   color: RISK_COLORS.caution },
                { level: 'critical',   label: 'Critical · 15–30 cm', color: RISK_COLORS.critical },
                { level: 'impassable', label: 'Impassable · &gt;30 cm', color: RISK_COLORS.impassable },
              ].map(({ level, label, color }) => (
                <div key={level} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}88`, flexShrink: 0 }} />
                  <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)' }} dangerouslySetInnerHTML={{ __html: label }} />
                </div>
              ))}
            </div>
          </div>

          {/* Timeline scrubber — bottom center */}
          <div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 10, width: 'min(620px, 92vw)' }}>
            <div style={{
              padding: '12px 18px', borderRadius: 16,
              background: 'rgba(8,13,26,0.96)', border: '1px solid rgba(255,255,255,0.1)',
              backdropFilter: 'blur(24px)', boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  onClick={togglePlay}
                  style={{
                    width: 30, height: 30, borderRadius: 8, border: 'none', cursor: 'pointer',
                    background: 'rgba(59,130,246,0.2)', color: '#93c5fd', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    transition: 'all 0.15s',
                  }}
                >
                  {isPlaying ? <Pause size={13} /> : <Play size={13} />}
                </button>

                <div style={{ flex: 1, position: 'relative' }}>
                  <input
                    type="range" min={0} max={180} step={15} value={timelineT}
                    onChange={e => handleSeek(Number(e.target.value))}
                    style={{ width: '100%', accentColor: '#3b82f6' }}
                  />
                  {/* Snapshot markers */}
                  <div style={{ position: 'absolute', top: -2, left: 0, right: 0, pointerEvents: 'none', display: 'flex' }}>
                    {snapshots.map(t => (
                      <div key={t} style={{
                        position: 'absolute',
                        left: `${(t / 180) * 100}%`,
                        width: 3, height: 3, borderRadius: '50%',
                        background: '#3b82f6', transform: 'translateX(-50%)',
                        boxShadow: '0 0 4px #3b82f6',
                      }} />
                    ))}
                  </div>
                </div>

                <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: 'rgba(255,255,255,0.6)', minWidth: 64, textAlign: 'right' }}>
                  T+{timelineT}m
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, paddingLeft: 40, paddingRight: 12 }}>
                {[0, 30, 60, 90, 120, 150, 180].map(t => (
                  <button
                    key={t}
                    onClick={() => handleSeek(t)}
                    style={{
                      fontSize: 9, padding: '2px 6px', borderRadius: 4, border: 'none', cursor: 'pointer',
                      background: timelineT === t ? 'rgba(59,130,246,0.25)' : 'transparent',
                      color: snapshots.includes(t) ? '#60a5fa' : 'rgba(255,255,255,0.2)',
                      fontFamily: 'JetBrains Mono, monospace',
                      transition: 'all 0.1s',
                    }}
                  >
                    +{t}m
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Scenario badge bottom-right on map */}
          {activeScenarioData && (
            <div style={{
              position: 'absolute', bottom: 96, right: showPanel ? 16 : 16, zIndex: 10,
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 10,
              background: `${activeScenarioData.color}18`,
              border: `1px solid ${activeScenarioData.color}44`,
              backdropFilter: 'blur(12px)',
              fontSize: 11, color: activeScenarioData.color, fontWeight: 600,
            }}>
              {activeScenarioData.icon} {activeScenarioData.label} · {activeScenarioData.sublabel}
            </div>
          )}
        </div>

        {/* ── Right sidebar panel ────────────────────────────────────── */}
        {showPanel && (
          <aside style={{
            width: 280, display: 'flex', flexDirection: 'column', gap: 0,
            background: 'rgba(8,13,26,0.97)', borderLeft: '1px solid rgba(255,255,255,0.08)',
            overflow: 'hidden',
          }}>
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10, padding: 12 }}>

              {/* Search */}
              <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 10 }}>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input
                    value={geocodeQ}
                    onChange={e => setGeocodeQ(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleGeocode()}
                    placeholder="Search landmark…"
                    style={{
                      flex: 1, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: 8, padding: '7px 10px', fontSize: 12, color: 'var(--text)',
                      outline: 'none', fontFamily: 'Inter, sans-serif',
                    }}
                  />
                  <button
                    onClick={handleGeocode}
                    style={{
                      padding: '0 10px', borderRadius: 8, border: 'none', cursor: 'pointer',
                      background: 'rgba(59,130,246,0.2)', color: '#93c5fd',
                    }}
                  >
                    <Search size={13} />
                  </button>
                </div>
                {geocodeResult && (
                  <div style={{ marginTop: 6, fontSize: 10, color: '#c084fc', padding: '4px 6px', background: 'rgba(192,132,252,0.1)', borderRadius: 6 }}>
                    📍 {geocodeResult.address?.split(',').slice(0, 2).join(',')}
                  </div>
                )}
              </div>

              {/* Route Planner */}
              <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 12 }}>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10 }}>Route Planner</div>

                {/* Vehicle selector */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4, marginBottom: 10 }}>
                  {[
                    { id: 'car',         label: 'Car',   icon: '🚗' },
                    { id: 'suv',         label: 'SUV',   icon: '🚙' },
                    { id: 'fire_tender', label: 'Fire',  icon: '🚒' },
                    { id: 'bus',         label: 'Bus',   icon: '🚌' },
                  ].map(v => (
                    <button
                      key={v.id}
                      onClick={() => setVehicleClass(v.id)}
                      style={{
                        padding: '5px 4px', borderRadius: 8, border: vehicleClass === v.id ? '1px solid rgba(59,130,246,0.4)' : '1px solid transparent',
                        background: vehicleClass === v.id ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
                        cursor: 'pointer', fontSize: 10, color: vehicleClass === v.id ? '#93c5fd' : 'rgba(255,255,255,0.4)',
                        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, transition: 'all 0.15s',
                      }}
                    >
                      <span>{v.icon}</span>
                      <span>{v.label}</span>
                    </button>
                  ))}
                </div>

                {routeState.step === 'idle' ? (
                  <button
                    onClick={() => setRouteState({ step: 'selecting_start' })}
                    style={{
                      width: '100%', padding: '9px', borderRadius: 10, border: 'none', cursor: 'pointer',
                      background: 'linear-gradient(135deg, rgba(59,130,246,0.3), rgba(37,99,235,0.2))',
                      color: '#93c5fd', fontSize: 12, fontWeight: 600, display: 'flex',
                      alignItems: 'center', justifyContent: 'center', gap: 6,
                      boxShadow: '0 0 20px rgba(59,130,246,0.15)',
                      transition: 'all 0.15s',
                    }}
                  >
                    <Navigation size={14} />
                    Plan Flood-Safe Route
                  </button>
                ) : (
                  <button
                    onClick={clearRoute}
                    style={{
                      width: '100%', padding: '9px', borderRadius: 10, border: '1px solid rgba(239,68,68,0.3)',
                      background: 'rgba(239,68,68,0.1)', color: '#fca5a5', fontSize: 12,
                      cursor: 'pointer', transition: 'all 0.15s',
                    }}
                  >
                    <X size={13} style={{ display: 'inline', marginRight: 4 }} />
                    Clear Route
                  </button>
                )}

                {/* Route result */}
                {routeResult && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{
                      padding: '8px 10px', borderRadius: 8, marginBottom: 6,
                      background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 10, color: '#4ade80', fontWeight: 600 }}>🟢 Safe Route</span>
                        <span style={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: '#86efac' }}>
                          {(routeResult.safe_route.distance_m / 1000).toFixed(1)}km · max {routeResult.safe_route.max_depth_cm.toFixed(0)}cm
                        </span>
                      </div>
                    </div>
                    <div style={{
                      padding: '8px 10px', borderRadius: 8, marginBottom: 6,
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>⚫ Naive Route</span>
                        <span style={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: 'rgba(255,255,255,0.3)' }}>
                          {(routeResult.naive_route.distance_m / 1000).toFixed(1)}km · max {routeResult.naive_route.max_depth_cm.toFixed(0)}cm
                        </span>
                      </div>
                    </div>
                    {routeResult.comparison.max_depth_avoided_cm > 0 && (
                      <div style={{ fontSize: 10, color: '#6ee7b7', textAlign: 'center', padding: '4px', background: 'rgba(34,197,94,0.06)', borderRadius: 6 }}>
                        <Shield size={10} style={{ display: 'inline', marginRight: 3 }} />
                        Avoids {routeResult.comparison.max_depth_avoided_cm.toFixed(0)}cm deeper water
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* What-If Controls */}
              <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 12 }}>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10 }}>What-If Scenario</div>
                <div style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11 }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)' }}>Drain blockage</span>
                    <span style={{ color: '#fbbf24', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>{blockagePct}%</span>
                  </div>
                  <input
                    type="range" min={0} max={100} step={10} value={blockagePct}
                    onChange={e => setBlockagePct(Number(e.target.value))}
                    style={{ width: '100%', accentColor: '#f59e0b' }}
                  />
                  {/* Visual blockage scale */}
                  <div style={{ display: 'flex', gap: 2, marginTop: 6 }}>
                    {[0,10,20,30,40,50,60,70,80,90,100].map(v => (
                      <div key={v} style={{
                        flex: 1, height: 3, borderRadius: 2,
                        background: v <= blockagePct ? '#f59e0b' : 'rgba(255,255,255,0.08)',
                        transition: 'background 0.15s',
                      }} />
                    ))}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    onClick={handleBlockageApply}
                    style={{
                      flex: 1, padding: '7px', borderRadius: 8, border: '1px solid rgba(245,158,11,0.3)',
                      background: 'rgba(245,158,11,0.12)', color: '#fbbf24', fontSize: 11,
                      cursor: 'pointer', fontWeight: 500, transition: 'all 0.15s',
                    }}
                  >
                    <Zap size={11} style={{ display: 'inline', marginRight: 3 }} />
                    Apply
                  </button>
                  <button
                    onClick={handleRetrain}
                    disabled={retraining}
                    style={{
                      flex: 1, padding: '7px', borderRadius: 8, border: '1px solid rgba(168,85,247,0.3)',
                      background: 'rgba(168,85,247,0.12)', color: '#c084fc', fontSize: 11,
                      cursor: retraining ? 'not-allowed' : 'pointer', opacity: retraining ? 0.6 : 1,
                      fontWeight: 500, transition: 'all 0.15s',
                    }}
                  >
                    {retraining ? <RefreshCw size={10} style={{ display: 'inline', marginRight: 3, animation: 'spin 1s linear infinite' }} /> : null}
                    {retraining ? 'Training…' : 'Retrain AI'}
                  </button>
                </div>
              </div>

              {/* PySTEPS Nowcast */}
              {nowcast && (
                <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 12 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Droplets size={10} />
                    PySTEPS Nowcast
                  </div>
                  {Object.entries(nowcast.forecasts_mm_hr).map(([t, v]) => (
                    <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', minWidth: 32, fontFamily: 'JetBrains Mono, monospace' }}>+{t}m</span>
                      <div style={{ flex: 1, height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%', borderRadius: 4,
                          background: `linear-gradient(90deg, #3b82f6, #6366f1)`,
                          width: `${Math.min(100, (v.mean_mm_hr / 80) * 100)}%`,
                          transition: 'width 0.5s ease',
                        }} />
                      </div>
                      <span style={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: '#93c5fd', minWidth: 52, textAlign: 'right' }}>{v.mean_mm_hr.toFixed(1)} mm/h</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Hotspot Incidents */}
              {(floodState?.hotspots?.length ?? 0) > 0 && (
                <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 12 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}><AlertTriangle size={10} />Flood Hotspots</span>
                    <span style={{ background: 'rgba(239,68,68,0.2)', color: '#f87171', padding: '1px 6px', borderRadius: 4, fontSize: 9 }}>{floodState!.hotspots.length}</span>
                  </div>
                  {floodState!.hotspots.slice(0, 5).map((h: any) => (
                    <div key={h.cluster_id} style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '7px 0', borderBottom: '1px solid rgba(255,255,255,0.05)',
                    }}>
                      <div style={{
                        width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                        background: h.severity === 'critical' ? '#ef4444' : '#f59e0b',
                        boxShadow: `0 0 6px ${h.severity === 'critical' ? '#ef4444' : '#f59e0b'}88`,
                        animation: 'pulse 2s infinite',
                      }} />
                      <div style={{ flex: 1, fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>Zone #{h.cluster_id} · {h.cell_count} cells</div>
                      <span style={{
                        fontSize: 10, fontFamily: 'JetBrains Mono, monospace',
                        color: h.severity === 'critical' ? '#f87171' : '#fbbf24', fontWeight: 600,
                      }}>{h.max_depth_cm.toFixed(0)}cm</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Model Accuracy */}
              {validation && (
                <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 12 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <TrendingUp size={10} />
                    Model Accuracy
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <div style={{ textAlign: 'center', padding: '10px 8px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.15)', borderRadius: 10 }}>
                      <div style={{ fontSize: 18, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: '#fbbf24', lineHeight: 1 }}>{validation.rmse_cm?.toFixed(1) ?? '—'}<span style={{ fontSize: 10 }}>cm</span></div>
                      <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>RMSE Error</div>
                    </div>
                    <div style={{ textAlign: 'center', padding: '10px 8px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.15)', borderRadius: 10 }}>
                      <div style={{ fontSize: 18, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: '#4ade80', lineHeight: 1 }}>{((validation.f1_flood_detection ?? 0) * 100).toFixed(0)}<span style={{ fontSize: 10 }}>%</span></div>
                      <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>F1 Score</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Activity log */}
              {alerts.length > 0 && (
                <div style={{ background: 'var(--surface-card)', border: '1px solid var(--surface-border)', borderRadius: 12, padding: 12 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Bell size={10} />Activity Log
                  </div>
                  {alerts.map((a, i) => (
                    <div key={i} style={{
                      fontSize: 10, color: 'rgba(255,255,255,0.45)', padding: '4px 0',
                      borderBottom: i < alerts.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                    }}>
                      {a}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </aside>
        )}

        {/* Panel toggle button */}
        <button
          onClick={() => setShowPanel(p => !p)}
          style={{
            position: 'absolute', right: showPanel ? 280 : 0, top: '50%', transform: 'translateY(-50%)',
            zIndex: 30, width: 18, height: 48, border: 'none', cursor: 'pointer',
            background: 'rgba(255,255,255,0.08)', borderRadius: showPanel ? '6px 0 0 6px' : '0 6px 6px 0',
            color: 'rgba(255,255,255,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'all 0.2s ease',
          }}
          title={showPanel ? 'Hide panel' : 'Show panel'}
        >
          <ChevronRight size={11} style={{ transform: showPanel ? 'none' : 'rotate(180deg)', transition: 'transform 0.2s' }} />
        </button>
      </main>
    </div>
  );
}
