'use client';

import dynamic from 'next/dynamic';
import { useState, useCallback, useEffect } from 'react';
import { useFloodStream } from '@/hooks/useFloodStream';
import { useMapInteraction } from '@/hooks/useMapInteraction';
import { api } from '@/lib/api';
import type { GeoJSONFeatureCollection } from '@/types/flood';
import {
  Navigation, Map, BarChart2, Waves, MousePointer2, X,
  Shield, CheckCircle, AlertTriangle, TrendingDown, Clock,
} from 'lucide-react';
import Link from 'next/link';

const FloodMap = dynamic(() => import('@/components/map/FloodMap'), { ssr: false });

const VEHICLE_OPTIONS = [
  { id: 'car',         label: 'Car',   icon: '🚗', desc: 'Clearance: 15cm max' },
  { id: 'suv',         label: 'SUV',   icon: '🚙', desc: 'Clearance: 25cm max' },
  { id: 'fire_tender', label: 'Fire',  icon: '🚒', desc: 'Emergency: 30cm max' },
  { id: 'bus',         label: 'Bus',   icon: '🚌', desc: 'Transit: 20cm max' },
];

const ROUTE_PRESETS: Array<{ label: string; start: [number, number]; end: [number, number] }> = [
  { label: '⚠️ Avoid Flood (South → North)', start: [13.095, 80.211], end: [13.108, 80.211] },
  { label: 'Tower → Roundtana', start: [13.088, 80.214], end: [13.085, 80.218] },
  { label: 'Thirumangalam → Shenoy', start: [13.085, 80.198], end: [13.078, 80.226] },
  { label: 'K4 Police → 100ft Rd', start: [13.090, 80.207], end: [13.080, 80.210] },
];

export default function RoutePlannerPage() {
  const { state: liveState, connected } = useFloodStream();
  const [vehicleClass, setVehicleClass] = useState('car');
  const {
    routeState, hoveredNodeId,
    startRouteSelection, handleMapClick, clearRoute, setHoveredNodeId, setPresetRoute,
  } = useMapInteraction({ vehicleClass });
  const [networkGeoJSON, setNetworkGeoJSON] = useState<GeoJSONFeatureCollection | null>(null);
  const [floodState, setFloodState] = useState<any>(null);

  const loadData = useCallback(() => {
    Promise.all([
      api.getFloodState().catch(() => null),
      api.getNetworkGraph().catch(() => null),
    ]).then(([state, graph]) => {
      if (state) setFloodState(state);
      if (graph) setNetworkGeoJSON(graph);
    });
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData]);

  useEffect(() => {
    if (liveState) {
      loadData();
    }
  }, [liveState, loadData]);

  const routeResult = routeState.step === 'done' ? routeState.result : null;

  const hint =
    routeState.step === 'idle'            ? null :
    routeState.step === 'selecting_start' ? 'Click to set START point' :
    routeState.step === 'selecting_end'   ? 'Click to set END point' :
    routeState.step === 'computing'       ? 'Computing safest route…' : null;

  const formatDistance = (m: number) => m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;

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
          <Shield size={14} color="#22c55e" />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Route Planner</span>
        </div>

        <div className={`status-badge ${connected ? 'live' : 'offline'}`}>
          <div className={`status-dot ${connected ? 'animate-pulse' : ''}`} />
          {connected ? 'Live flood data' : 'Disconnected'}
        </div>

        <div style={{ flex: 1 }} />

        <nav style={{ display: 'flex', gap: 2 }}>
          <Link href="/" className="nav-link"><Map size={13} />Dashboard</Link>
          <Link href="/route-planner" className="nav-link active"><Navigation size={13} />Route Planner</Link>
          <Link href="/analytics" className="nav-link"><BarChart2 size={13} />Analytics</Link>
        </nav>
      </header>

      <main style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Full-screen map */}
        <div style={{ flex: 1, position: 'relative' }}>
          <FloodMap
            floodState={floodState}
            networkGeoJSON={networkGeoJSON}
            routeResult={routeResult}
            routeState={routeState}
            onMapClick={handleMapClick}
            onNodeHover={id => setHoveredNodeId(id)}
          />

          {/* Bottom-left: Road Flooding & Route Legend */}
          <div style={{
            position: 'absolute', bottom: 24, left: 16, zIndex: 10,
            background: 'rgba(8,13,26,0.92)', border: '1px solid rgba(255,255,255,0.09)',
            borderRadius: 12, backdropFilter: 'blur(20px)', padding: '10px 14px',
            display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11,
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          }}>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.4)', marginBottom: 2 }}>
              Road Flood Status & Routing
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 14, height: 4, borderRadius: 2, background: '#22c55e' }} />
              <span style={{ color: '#86efac', fontWeight: 600 }}>Flood-Safe Detour</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 14, height: 3, borderTop: '2px dashed #94a3b8' }} />
              <span style={{ color: 'rgba(255,255,255,0.6)' }}>Standard Path (Flooded)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 14, height: 4, borderRadius: 2, background: '#f59e0b', boxShadow: '0 0 6px #f59e0b' }} />
              <span style={{ color: '#fbbf24' }}>Caution Road Inundation (5–15cm)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 14, height: 5, borderRadius: 2, background: '#f97316', boxShadow: '0 0 8px #f97316' }} />
              <span style={{ color: '#fb923c' }}>Critical Flooded Road (15–30cm)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 14, height: 6, borderRadius: 2, background: '#ef4444', boxShadow: '0 0 10px #ef4444' }} />
              <span style={{ color: '#f87171' }}>Impassable Road (&gt;30cm)</span>
            </div>
          </div>

          {/* Top-left: Route control panel */}
          <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10, display: 'flex', flexDirection: 'column', gap: 10, width: 280 }}>

            {/* Vehicle selector */}
            <div style={{
              background: 'rgba(8,13,26,0.94)', border: '1px solid rgba(255,255,255,0.09)',
              borderRadius: 14, backdropFilter: 'blur(20px)', padding: 14,
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            }} className="animate-slide-up">
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10 }}>Vehicle Type</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
                {VEHICLE_OPTIONS.map(v => (
                  <button
                    key={v.id}
                    onClick={() => setVehicleClass(v.id)}
                    title={v.desc}
                    style={{
                      padding: '8px 4px', borderRadius: 10,
                      border: vehicleClass === v.id ? '1px solid rgba(59,130,246,0.45)' : '1px solid rgba(255,255,255,0.06)',
                      background: vehicleClass === v.id ? 'rgba(59,130,246,0.18)' : 'rgba(255,255,255,0.04)',
                      cursor: 'pointer', fontSize: 10,
                      color: vehicleClass === v.id ? '#93c5fd' : 'rgba(255,255,255,0.4)',
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                      transition: 'all 0.15s',
                    }}
                  >
                    <span style={{ fontSize: 16 }}>{v.icon}</span>
                    <span style={{ fontWeight: 500 }}>{v.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Plan button / status */}
            {routeState.step === 'idle' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button
                  id="start-route-btn"
                  onClick={startRouteSelection}
                  style={{
                    padding: '12px 18px', borderRadius: 12, border: 'none', cursor: 'pointer',
                    background: 'linear-gradient(135deg, #3b82f6, #2563eb)',
                    color: '#fff', fontSize: 13, fontWeight: 600,
                    display: 'flex', alignItems: 'center', gap: 8,
                    boxShadow: '0 0 30px rgba(59,130,246,0.35), 0 4px 16px rgba(0,0,0,0.3)',
                    transition: 'all 0.2s ease',
                  }}
                  className="animate-slide-up"
                >
                  <Navigation size={15} />
                  Plan Flood-Safe Route
                </button>

                {/* Quick Presets */}
                <div style={{
                  background: 'rgba(8,13,26,0.92)', border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 12, backdropFilter: 'blur(16px)', padding: 10,
                }} className="animate-slide-up">
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 6 }}>
                    Quick Corridors
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {ROUTE_PRESETS.map((p, idx) => (
                      <button
                        key={idx}
                        onClick={() => setPresetRoute(p.start, p.end)}
                        style={{
                          padding: '6px 8px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)',
                          background: 'rgba(255,255,255,0.03)', color: '#93c5fd', fontSize: 11,
                          cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          transition: 'all 0.15s ease',
                        }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(59,130,246,0.15)'; }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)'; }}
                      >
                        <span>{p.label}</span>
                        <Navigation size={10} style={{ opacity: 0.6 }} />
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : hint && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '12px 16px', borderRadius: 12,
                background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.3)',
                backdropFilter: 'blur(16px)',
              }} className="animate-slide-up">
                <MousePointer2 size={14} color="#93c5fd" style={{ animation: 'pulse 2s infinite', flexShrink: 0 }} />
                <span style={{ flex: 1, fontSize: 12, color: '#93c5fd', fontWeight: 500 }}>{hint}</span>
                <button
                  onClick={clearRoute}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.35)', padding: 2 }}
                >
                  <X size={14} />
                </button>
              </div>
            )}
          </div>

          {/* Route result card — top right */}
          {routeResult && (
            <div style={{
              position: 'absolute', top: 16, right: 16, zIndex: 10, width: 300,
            }} className="animate-slide-right">
              <div style={{
                background: 'rgba(8,13,26,0.96)', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 16, backdropFilter: 'blur(24px)',
                boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
                overflow: 'hidden',
              }}>
                {/* Header */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.07)',
                  background: 'rgba(34,197,94,0.06)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <CheckCircle size={15} color="#22c55e" />
                    <span style={{ fontSize: 13, fontWeight: 700 }}>Route Comparison</span>
                  </div>
                  <button
                    onClick={clearRoute}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.35)', padding: 4 }}
                  >
                    <X size={14} />
                  </button>
                </div>

                <div style={{ padding: 14 }}>
                  {/* Safe route */}
                  <div style={{
                    padding: '10px 12px', borderRadius: 10, marginBottom: 8,
                    background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.2)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                      <div style={{ width: 16, height: 3, background: '#22c55e', borderRadius: 2 }} />
                      <span style={{ fontSize: 11, fontWeight: 700, color: '#4ade80' }}>Flood-Safe Route</span>
                    </div>
                    <div style={{ display: 'flex', gap: 16 }}>
                      <div>
                        <div style={{ fontSize: 20, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: '#fff', lineHeight: 1 }}>
                          {routeResult.safe_route.max_depth_cm.toFixed(1)}<span style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>cm</span>
                        </div>
                        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>max depth</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 20, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: '#fff', lineHeight: 1 }}>
                          {formatDistance(routeResult.safe_route.distance_m)}
                        </div>
                        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>distance</div>
                      </div>
                    </div>
                  </div>

                  {/* Naive route */}
                  <div style={{
                    padding: '10px 12px', borderRadius: 10, marginBottom: 12,
                    background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                      <div style={{ width: 16, height: 2, borderTop: '2px dashed #94a3b8', background: 'none' }} />
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.4)' }}>Naive Shortest Route</span>
                    </div>
                    <div style={{ display: 'flex', gap: 16 }}>
                      <div>
                        <div style={{ fontSize: 20, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: 'rgba(255,255,255,0.4)', lineHeight: 1 }}>
                          {routeResult.naive_route.max_depth_cm.toFixed(1)}<span style={{ fontSize: 11 }}>cm</span>
                        </div>
                        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>max depth</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 20, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: 'rgba(255,255,255,0.4)', lineHeight: 1 }}>
                          {formatDistance(routeResult.naive_route.distance_m)}
                        </div>
                        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>distance</div>
                      </div>
                    </div>
                  </div>

                  {/* Comparison stats */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginBottom: routeResult.comparison.max_depth_avoided_cm > 0 ? 10 : 0 }}>
                    {[
                      {
                        icon: <Clock size={12} />,
                        value: routeResult.comparison.distance_saved_m > 0
                          ? `-${formatDistance(routeResult.comparison.distance_saved_m)}`
                          : `+${formatDistance(Math.abs(routeResult.comparison.distance_saved_m))}`,
                        label: 'detour',
                        color: routeResult.comparison.distance_saved_m > 0 ? '#f87171' : 'rgba(255,255,255,0.6)',
                      },
                      {
                        icon: <AlertTriangle size={12} />,
                        value: `${routeResult.comparison.max_depth_avoided_cm.toFixed(1)}cm`,
                        label: 'avoided',
                        color: routeResult.comparison.max_depth_avoided_cm > 0 ? '#f87171' : 'rgba(255,255,255,0.6)',
                      },
                      {
                        icon: <TrendingDown size={12} />,
                        value: `${routeResult.comparison.safe_weight_ratio.toFixed(2)}x`,
                        label: 'safety',
                        color: '#fb923c',
                      },
                    ].map((stat, i) => (
                      <div key={i} style={{
                        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                        padding: '8px 6px', borderRadius: 8,
                        background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)',
                      }}>
                        <div style={{ color: stat.color }}>{stat.icon}</div>
                        <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: stat.color }}>{stat.value}</span>
                        <span style={{ fontSize: 8, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{stat.label}</span>
                      </div>
                    ))}
                  </div>

                  {routeResult.comparison.max_depth_avoided_cm > 0 && (
                    <div style={{
                      display: 'flex', alignItems: 'flex-start', gap: 8,
                      padding: '8px 10px', borderRadius: 8,
                      background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)',
                    }}>
                      <Shield size={12} color="#fbbf24" style={{ flexShrink: 0, marginTop: 1 }} />
                      <p style={{ fontSize: 11, color: '#fcd34d', margin: 0, lineHeight: 1.5 }}>
                        Safe route avoids up to {routeResult.comparison.max_depth_avoided_cm.toFixed(1)}cm deeper floodwater.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Bottom-center: instruction card when idle */}
          {!routeResult && routeState.step === 'idle' && (
            <div style={{ position: 'absolute', bottom: 32, left: '50%', transform: 'translateX(-50%)', zIndex: 10 }} className="animate-slide-up">
              <div style={{
                padding: '20px 28px', borderRadius: 16, textAlign: 'center', maxWidth: 340,
                background: 'rgba(8,13,26,0.94)', border: '1px solid rgba(255,255,255,0.09)',
                backdropFilter: 'blur(20px)', boxShadow: '0 20px 50px rgba(0,0,0,0.5)',
              }}>
                <div style={{
                  width: 44, height: 44, borderRadius: 12, margin: '0 auto 12px',
                  background: 'rgba(34,197,94,0.15)', border: '1px solid rgba(34,197,94,0.25)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Shield size={22} color="#22c55e" />
                </div>
                <h2 style={{ fontSize: 14, fontWeight: 700, marginBottom: 6, color: '#fff' }}>Flood-Safe Route Planner</h2>
                <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', lineHeight: 1.6, marginBottom: 14 }}>
                  Select your vehicle type, then click <strong style={{ color: 'rgba(255,255,255,0.7)' }}>&quot;Plan Flood-Safe Route&quot;</strong> and pick two points on the map.
                </p>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'center', fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>
                  <span>🗺️ Real-time flood data</span>
                  <span>·</span>
                  <span>⚡ AI-powered routing</span>
                  <span>·</span>
                  <span>🛡️ Risk-aware paths</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
