'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import {
  Waves, Navigation, BarChart2, Map, Play, Pause,
  AlertTriangle, CheckCircle, Activity, Gauge, RefreshCw,
  ChevronRight, Wind, Droplets, Search, Bell, X, MousePointer2,
} from 'lucide-react';
import { api, createFloodWebSocket } from '@/lib/api';
import type {
  FloodStateAPI, FloodSummary, GeoJSONCollection,
  RouteResult, WSFloodMessage, ScenarioParams, NowcastAPI,
} from '@/lib/api';
import type { RouteSelectionState } from '@/components/map/FloodMap';

const FloodMap = dynamic(() => import('@/components/map/FloodMap'), { ssr: false });

// ── Constants ──────────────────────────────────────────────────────────────
const RISK_COLORS = { safe: '#6b7280', caution: '#f59e0b', critical: '#f97316', impassable: '#ef4444' };
const RISK_LABELS = { safe: 'Safe (<5cm)', caution: 'Caution (5–15cm)', critical: 'Critical (15–30cm)', impassable: 'Impassable (>30cm)' };

const SCENARIOS = [
  { id: 'cloudburst_extreme', label: 'Cloudburst Extreme', dbz: 55, icon: '⛈️' },
  { id: 'monsoon_front',      label: 'Monsoon Front',      dbz: 45, icon: '🌧️' },
  { id: 'moderate_steady',    label: 'Moderate Steady',    dbz: 38, icon: '🌦️' },
  { id: 'light_drizzle',      label: 'Light Drizzle',      dbz: 25, icon: '🌂' },
];

// ─────────────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  // State
  const [floodState, setFloodState]       = useState<FloodStateAPI | null>(null);
  const [summary, setSummary]             = useState<FloodSummary | null>(null);
  const [network, setNetwork]             = useState<GeoJSONCollection | null>(null);
  const [nowcast, setNowcast]             = useState<NowcastAPI | null>(null);
  const [connected, setConnected]         = useState(false);
  const [lastTick, setLastTick]           = useState<Date | null>(null);
  const [activeScenario, setActiveScenario] = useState('cloudburst_extreme');
  const [isPlaying, setIsPlaying]         = useState(true);
  const [timelineT, setTimelineT]         = useState(0);
  const [isScrubbing, setIsScrubbing]     = useState(false);
  const [snapshots, setSnapshots]         = useState<number[]>([]);
  const [validation, setValidation]       = useState<{ rmse_cm?: number; f1_flood_detection?: number } | null>(null);
  const [geocodeQ, setGeocodeQ]           = useState('');
  const [geocodeResult, setGeocodeResult] = useState<{ lat: number; lon: number; address: string } | null>(null);
  const [blockagePct, setBlockagePct]     = useState(0);
  const [retraining, setRetraining]       = useState(false);
  const [alerts, setAlerts]               = useState<string[]>([]);

  // Route state
  const [routeState, setRouteState] = useState<RouteSelectionState>({ step: 'idle' });
  const [routeResult, setRouteResult] = useState<RouteResult | null>(null);
  const [vehicleClass, setVehicleClass] = useState('car');
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  // ── Load static data ────────────────────────────────────────────────────
  useEffect(() => {
    api.getNetworkGraph().then(setNetwork).catch(console.error);
    api.listSnapshots().then(s => setSnapshots(s.available_minutes)).catch(console.error);
    api.getValidation().then(setValidation).catch(console.error);
    api.getNowcast().then(setNowcast).catch(console.error);
  }, []);

  // ── WebSocket flood stream ───────────────────────────────────────────────
  useEffect(() => {
    const connect = () => {
      const ws = createFloodWebSocket(
        (msg: WSFloodMessage) => {
          setLastTick(new Date());
          if (!isScrubbing) setTimelineT(msg.t_minutes);
          // Pull full state
          api.getFloodState().then(s => {
            setFloodState(s);
            if (s.validation) setValidation(s.validation);
          }).catch(console.error);
          api.getFloodSummary().then(setSummary).catch(console.error);
        },
        () => setConnected(true),
      );
      ws.onopen    = () => setConnected(true);
      ws.onclose   = () => { setConnected(false); setTimeout(connect, 3000); };
      wsRef.current = ws;
    };
    connect();
    return () => wsRef.current?.close();
  }, []);

  // ── Scenario controls ────────────────────────────────────────────────────
  const handleScenario = useCallback(async (id: string, dbz: number) => {
    setActiveScenario(id);
    await api.runScenario({
      scenario: id, intensity_dbz: dbz,
      storm_center: [0.45, 0.55], radius_fraction: 0.25,
      drain_blockage_pct: blockagePct,
    });
    addAlert(`Scenario switched to: ${id}`);
  }, [blockagePct]);

  const handleBlockageApply = useCallback(async () => {
    const sc = SCENARIOS.find(s => s.id === activeScenario)!;
    await api.runScenario({
      scenario: activeScenario, intensity_dbz: sc.dbz,
      storm_center: [0.45, 0.55], radius_fraction: 0.25,
      drain_blockage_pct: blockagePct,
    });
    addAlert(`Drain blockage what-if: ${blockagePct}%`);
  }, [activeScenario, blockagePct]);

  const handleRetrain = useCallback(async () => {
    setRetraining(true);
    await api.retrainBlockage();
    setRetraining(false);
    addAlert('Blockage model retrained — flood outcomes updated');
  }, []);

  // ── Timeline scrub ───────────────────────────────────────────────────────
  const handleSeek = useCallback(async (t: number) => {
    setTimelineT(t);
    setIsScrubbing(true);
    const snap = await api.getFloodState(t).catch(() => null);
    if (snap) setFloodState(snap);
    setTimeout(() => setIsScrubbing(false), 4000);
  }, []);

  // ── Route selection ──────────────────────────────────────────────────────
  const handleMapClick = useCallback(async (lat: number, lon: number) => {
    if (routeState.step === 'selecting_start') {
      setRouteState({ step: 'selecting_end', start: { lat, lon } });
    } else if (routeState.step === 'selecting_end') {
      const { start } = routeState;
      setRouteState({ step: 'computing', start, end: { lat, lon } });
      try {
        const result = await api.computeRoute(
          [start.lat, start.lon], [lat, lon], vehicleClass
        );
        setRouteResult(result);
        setRouteState({ step: 'done', start, end: { lat, lon }, result });
        addAlert(`Route computed — safe distance: ${(result.safe_route.distance_m / 1000).toFixed(1)} km`);
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

  // ── Geocode ──────────────────────────────────────────────────────────────
  const handleGeocode = useCallback(async () => {
    const result = await api.geocode(geocodeQ).catch(() => null);
    if (result && !('error' in result)) setGeocodeResult(result);
  }, [geocodeQ]);

  // ── Alerts panel ─────────────────────────────────────────────────────────
  const addAlert = (msg: string) => {
    setAlerts(prev => [msg, ...prev].slice(0, 10));
  };

  const routeHint =
    routeState.step === 'selecting_start' ? '📍 Click map to set START point' :
    routeState.step === 'selecting_end'   ? '🏁 Click map to set END point'  :
    routeState.step === 'computing'       ? '⏳ Computing flood-safe route…'  : null;

  return (
    <div className="h-screen flex flex-col bg-[#0a0f1e] text-white overflow-hidden font-[Inter,sans-serif]">
      {/* ── Top Bar ─────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-3 px-4 h-12 bg-[#0d1428]/90 backdrop-blur border-b border-white/10 z-20 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Waves className="w-5 h-5 text-blue-400" />
          <span className="font-bold text-sm tracking-tight">UrbanFlow v2</span>
          <span className="text-[10px] text-white/40 hidden sm:inline">Anna Nagar · SIH 2026</span>
        </div>

        {/* Live indicator */}
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${
          connected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
          {connected ? 'Live' : 'Offline'}
        </div>

        {/* Scenario selector */}
        <div className="flex items-center gap-1 ml-2">
          {SCENARIOS.map(s => (
            <button key={s.id}
              onClick={() => handleScenario(s.id, s.dbz)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
                activeScenario === s.id
                  ? 'bg-blue-500/30 text-blue-300 border border-blue-500/50'
                  : 'text-white/50 hover:text-white hover:bg-white/10'
              }`}>
              {s.icon} {s.label}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        {/* Validation accuracy */}
        {validation?.rmse_cm !== undefined && (
          <div className="flex items-center gap-3 text-[11px] text-white/50">
            <span>RMSE: <span className="text-amber-400 font-mono">{validation.rmse_cm.toFixed(1)}cm</span></span>
            <span>F1: <span className="text-green-400 font-mono">{(validation.f1_flood_detection ?? 0).toFixed(2)}</span></span>
          </div>
        )}

        {/* Nav */}
        <nav className="flex items-center gap-1 ml-2">
          <Link href="/" className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-500/20 text-blue-300 text-[11px]">
            <Map className="w-3 h-3" /> Dashboard
          </Link>
          <Link href="/route-planner" className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-white/50 hover:text-white text-[11px] transition-colors">
            <Navigation className="w-3 h-3" /> Route Planner
          </Link>
          <Link href="/analytics" className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-white/50 hover:text-white text-[11px] transition-colors">
            <BarChart2 className="w-3 h-3" /> Analytics
          </Link>
        </nav>
      </header>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <main className="flex-1 relative overflow-hidden flex">
        {/* Map hero */}
        <div className="flex-1 relative">
          <FloodMap
            networkGeoJSON={network}
            floodNodes={floodState?.nodes ?? []}
            routeResult={routeResult}
            routeState={routeState}
            onMapClick={handleMapClick}
            onNodeHover={setHoveredNodeId}
          />

          {/* Route hint banner */}
          {routeHint && (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10
              flex items-center gap-2 px-4 py-2 rounded-xl
              bg-blue-500/20 border border-blue-500/40 backdrop-blur-sm text-sm font-medium text-blue-300">
              <MousePointer2 className="w-4 h-4 animate-pulse" />
              {routeHint}
              <button onClick={clearRoute} className="ml-1 text-white/40 hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Stats bar */}
          {summary && (
            <div className="absolute top-3 left-3 z-10">
              <div className="flex items-center gap-4 px-4 py-2 rounded-xl
                bg-[#0d1428]/90 backdrop-blur border border-white/10 text-[11px]">
                {[
                  { label: 'Max Depth', value: `${summary.max_depth_cm.toFixed(1)}cm`, color: '#f97316' },
                  { label: 'Impassable', value: `${summary.impassable_pct.toFixed(1)}%`, color: '#ef4444' },
                  { label: 'Critical', value: `${summary.critical_pct.toFixed(1)}%`, color: '#f97316' },
                  { label: 'Hotspots', value: String(summary.hotspots.length), color: '#f59e0b' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="text-center">
                    <div className="font-mono font-bold text-sm" style={{ color }}>{value}</div>
                    <div className="text-white/40">{label}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Risk legend */}
          <div className="absolute bottom-24 left-3 z-10">
            <div className="px-3 py-2.5 rounded-xl bg-[#0d1428]/90 backdrop-blur border border-white/10">
              <div className="text-[9px] font-semibold text-white/40 uppercase tracking-widest mb-2">Risk Bands</div>
              {Object.entries(RISK_LABELS).map(([level, label]) => (
                <div key={level} className="flex items-center gap-2 mb-1 last:mb-0">
                  <div className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ background: RISK_COLORS[level as keyof typeof RISK_COLORS] }} />
                  <span className="text-[10px] text-white/60">{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Timeline scrubber */}
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 w-[min(600px,90vw)]">
            <div className="px-4 py-3 rounded-xl bg-[#0d1428]/95 backdrop-blur border border-white/10">
              <div className="flex items-center gap-3">
                <button onClick={() => setIsPlaying(p => !p)}
                  className="w-7 h-7 flex items-center justify-center rounded-lg bg-blue-500/20 text-blue-300 hover:bg-blue-500/30">
                  {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                </button>
                <input type="range" min={0} max={180} step={15} value={timelineT}
                  onChange={e => handleSeek(Number(e.target.value))}
                  className="flex-1 accent-blue-500 cursor-pointer" />
                <span className="text-[11px] font-mono text-white/60 w-16 text-right">
                  T+{timelineT}min
                </span>
              </div>
              <div className="flex justify-between mt-1.5 px-8">
                {[0, 15, 30, 60, 120, 180].map(t => (
                  <button key={t} onClick={() => handleSeek(t)}
                    className={`text-[9px] px-1.5 py-0.5 rounded transition-colors ${
                      snapshots.includes(t)
                        ? 'text-blue-400 hover:bg-blue-500/20'
                        : 'text-white/20'
                    }`}>
                    +{t}m
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Geocode result dot */}
          {geocodeResult && (
            <div className="absolute top-3 right-80 z-10 text-[11px] bg-purple-500/20 border border-purple-500/40
              px-3 py-1.5 rounded-lg text-purple-300 backdrop-blur">
              📍 {geocodeResult.address?.split(',')[0]}
            </div>
          )}
        </div>

        {/* ── Right Panel ──────────────────────────────────────────────── */}
        <div className="w-72 flex flex-col gap-2 p-3 bg-[#0a0f1e]/95 border-l border-white/10 overflow-y-auto flex-shrink-0">

          {/* Geocode search [71] */}
          <div className="glass-card p-2">
            <div className="flex gap-1">
              <input value={geocodeQ} onChange={e => setGeocodeQ(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleGeocode()}
                placeholder="Search landmark…"
                className="flex-1 bg-white/5 text-white text-xs px-2.5 py-1.5 rounded-lg border border-white/10 outline-none focus:border-blue-500/50" />
              <button onClick={handleGeocode}
                className="p-1.5 rounded-lg bg-blue-500/20 text-blue-300 hover:bg-blue-500/30">
                <Search className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Route planner */}
          <div className="glass-card p-3">
            <div className="text-[10px] font-semibold text-white/40 uppercase tracking-widest mb-2">Route Planner</div>
            <div className="flex gap-1 mb-2">
              {['car', 'suv', 'fire_tender', 'bus'].map(vc => (
                <button key={vc} onClick={() => setVehicleClass(vc)}
                  className={`flex-1 py-1 rounded text-[10px] transition-all ${
                    vehicleClass === vc ? 'bg-blue-500/30 text-blue-300' : 'text-white/40 hover:text-white hover:bg-white/10'
                  }`}>
                  {vc === 'fire_tender' ? 'Fire' : vc.charAt(0).toUpperCase() + vc.slice(1)}
                </button>
              ))}
            </div>
            {routeState.step === 'idle' ? (
              <button onClick={() => setRouteState({ step: 'selecting_start' })}
                className="w-full py-2 rounded-lg bg-blue-500/20 text-blue-300 text-xs font-medium hover:bg-blue-500/30 transition-all">
                <Navigation className="w-3.5 h-3.5 inline mr-1" />
                Plan Flood-Safe Route
              </button>
            ) : routeState.step === 'done' ? (
              <button onClick={clearRoute}
                className="w-full py-2 rounded-lg bg-red-500/20 text-red-300 text-xs hover:bg-red-500/30 transition-all">
                Clear Route
              </button>
            ) : null}

            {/* Route result */}
            {routeResult && (
              <div className="mt-2 space-y-1.5">
                <div className="flex items-center justify-between p-2 rounded-lg bg-green-500/10 border border-green-500/20">
                  <span className="text-[10px] text-green-400">🟢 Safe route</span>
                  <span className="text-[10px] font-mono text-green-300">
                    {(routeResult.safe_route.distance_m / 1000).toFixed(1)}km
                    · max {routeResult.safe_route.max_depth_cm.toFixed(0)}cm
                  </span>
                </div>
                <div className="flex items-center justify-between p-2 rounded-lg bg-white/5">
                  <span className="text-[10px] text-white/50">⚫ Naive route</span>
                  <span className="text-[10px] font-mono text-white/40">
                    {(routeResult.naive_route.distance_m / 1000).toFixed(1)}km
                    · max {routeResult.naive_route.max_depth_cm.toFixed(0)}cm
                  </span>
                </div>
                {routeResult.comparison.max_depth_avoided_cm > 0 && (
                  <div className="text-[10px] text-emerald-400 text-center">
                    ↑ Avoids {routeResult.comparison.max_depth_avoided_cm.toFixed(0)}cm deeper water
                  </div>
                )}
              </div>
            )}
          </div>

          {/* What-if scenario controls [72] */}
          <div className="glass-card p-3">
            <div className="text-[10px] font-semibold text-white/40 uppercase tracking-widest mb-2">What-If Controls</div>
            <div className="mb-2">
              <div className="flex justify-between text-[10px] text-white/50 mb-1">
                <span>Drain blockage</span>
                <span className="font-mono text-amber-400">{blockagePct}%</span>
              </div>
              <input type="range" min={0} max={100} step={10} value={blockagePct}
                onChange={e => setBlockagePct(Number(e.target.value))}
                className="w-full accent-amber-500" />
            </div>
            <button onClick={handleBlockageApply}
              className="w-full py-1.5 rounded-lg bg-amber-500/20 text-amber-300 text-[10px] hover:bg-amber-500/30 mb-1 transition-all">
              Apply Blockage Scenario
            </button>
            <button onClick={handleRetrain} disabled={retraining}
              className="w-full py-1.5 rounded-lg bg-purple-500/20 text-purple-300 text-[10px] hover:bg-purple-500/30 transition-all disabled:opacity-50">
              {retraining ? <RefreshCw className="w-3 h-3 inline animate-spin mr-1" /> : null}
              {retraining ? 'Retraining…' : '⚡ Retrain Blockage Model [25]'}
            </button>
          </div>

          {/* Nowcast panel */}
          {nowcast && (
            <div className="glass-card p-3">
              <div className="text-[10px] font-semibold text-white/40 uppercase tracking-widest mb-2">PySTEPS Nowcast [14]</div>
              {Object.entries(nowcast.forecasts_mm_hr).map(([t, v]) => (
                <div key={t} className="flex items-center justify-between py-0.5">
                  <span className="text-[10px] text-white/50">+{t}min</span>
                  <div className="flex-1 mx-2 h-1.5 bg-white/10 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (v.mean_mm_hr / 100) * 100)}%` }} />
                  </div>
                  <span className="text-[10px] font-mono text-blue-300">{v.mean_mm_hr.toFixed(1)}mm/h</span>
                </div>
              ))}
            </div>
          )}

          {/* Hotspot incident feed */}
          {(floodState?.hotspots?.length ?? 0) > 0 && (
            <div className="glass-card p-3">
              <div className="text-[10px] font-semibold text-white/40 uppercase tracking-widest mb-2">
                Flood Hotspots [51] ({floodState!.hotspots.length})
              </div>
              {floodState!.hotspots.slice(0, 4).map(h => (
                <div key={h.cluster_id} className={`flex items-center gap-2 py-1.5 border-b border-white/5 last:border-0 ${
                  h.severity === 'critical' ? 'text-red-300' : 'text-amber-300'
                }`}>
                  <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                  <div className="flex-1 text-[10px]">
                    Zone #{h.cluster_id} — {h.cell_count} cells
                  </div>
                  <span className="text-[10px] font-mono">{h.max_depth_cm.toFixed(0)}cm</span>
                </div>
              ))}
            </div>
          )}

          {/* Model validation */}
          {validation && (
            <div className="glass-card p-3">
              <div className="text-[10px] font-semibold text-white/40 uppercase tracking-widest mb-2">Model Accuracy [64]</div>
              <div className="grid grid-cols-2 gap-2">
                <div className="text-center p-2 rounded-lg bg-white/5">
                  <div className="text-sm font-mono font-bold text-amber-400">
                    {validation.rmse_cm?.toFixed(1) ?? '—'}cm
                  </div>
                  <div className="text-[9px] text-white/40">RMSE</div>
                </div>
                <div className="text-center p-2 rounded-lg bg-white/5">
                  <div className="text-sm font-mono font-bold text-green-400">
                    {((validation.f1_flood_detection ?? 0) * 100).toFixed(0)}%
                  </div>
                  <div className="text-[9px] text-white/40">F1 Score</div>
                </div>
              </div>
            </div>
          )}

          {/* Alerts log */}
          {alerts.length > 0 && (
            <div className="glass-card p-3">
              <div className="text-[10px] font-semibold text-white/40 uppercase tracking-widest mb-2">
                <Bell className="w-3 h-3 inline mr-1" />Activity Log
              </div>
              {alerts.map((a, i) => (
                <div key={i} className="text-[9px] text-white/50 py-0.5 border-b border-white/5 last:border-0">
                  {a}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
