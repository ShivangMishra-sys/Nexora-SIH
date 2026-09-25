'use client';

import dynamic from 'next/dynamic';
import { useState, useCallback, useEffect } from 'react';
import { useFloodStream } from '@/hooks/useFloodStream';
import { useMapInteraction } from '@/hooks/useMapInteraction';
import RouteResultCard from '@/components/panels/RouteResultCard';
import { api } from '@/lib/api';
import type { GeoJSONFeatureCollection } from '@/types/flood';
import { Navigation, Map, BarChart2, Waves, MousePointer2, X, Shield } from 'lucide-react';
import Link from 'next/link';

const FloodMap = dynamic(() => import('@/components/map/FloodMap'), { ssr: false });

export default function RoutePlannerPage() {
  const { state: liveState, connected } = useFloodStream();
  const {
    routeState, hoveredNodeId,
    startRouteSelection, handleMapClick, clearRoute, setHoveredNodeId,
  } = useMapInteraction();
  const [networkGeoJSON, setNetworkGeoJSON] = useState<GeoJSONFeatureCollection | null>(null);

  useEffect(() => {
    api.getNetworkGraph().then(setNetworkGeoJSON).catch(console.error);
  }, []);

  const routeResult = routeState.step === 'done' ? routeState.result : null;

  const hint =
    routeState.step === 'idle'             ? 'Click "Plan Route" then click two points on the map' :
    routeState.step === 'selecting_start'  ? 'Click to set START point' :
    routeState.step === 'selecting_end'    ? 'Click to set END point' :
    routeState.step === 'computing'        ? 'Computing safest route…' : null;

  return (
    <div className="h-screen flex flex-col bg-navy overflow-hidden">
      {/* Top Bar */}
      <header className="top-bar">
        <div className="flex items-center gap-2 flex-shrink-0">
          <Waves className="w-5 h-5 text-accent" />
          <span className="font-bold text-base tracking-tight">UrbanFlow</span>
        </div>
        <div className="w-px h-5 bg-surface-border mx-1" />
        <Shield className="w-4 h-4 text-green-400" />
        <span className="text-sm font-semibold text-white">Route Planner</span>
        <span className={`ml-2 flex items-center gap-1 text-xs ${connected ? 'text-green-400' : 'text-muted'}`}>
          <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green-400 animate-pulse' : 'bg-muted'}`} />
          {connected ? 'Live flood data' : 'Disconnected'}
        </span>
        <div className="flex-1" />
        <nav className="flex items-center gap-1">
          <Link href="/" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg hover:bg-surface-card text-xs font-medium text-muted hover:text-white transition-colors">
            <Map className="w-3.5 h-3.5" />Dashboard
          </Link>
          <Link href="/route-planner" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/20 text-xs font-medium text-accent">
            <Navigation className="w-3.5 h-3.5" />Route Planner
          </Link>
          <Link href="/analytics" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg hover:bg-surface-card text-xs font-medium text-muted hover:text-white transition-colors">
            <BarChart2 className="w-3.5 h-3.5" />Analytics
          </Link>
        </nav>
      </header>

      <main className="flex-1 relative overflow-hidden">
        <FloodMap
          floodState={liveState}
          networkGeoJSON={networkGeoJSON}
          routeResult={routeResult}
          routeState={routeState}
          onMapClick={handleMapClick}
          onNodeHover={(id) => setHoveredNodeId(id)}
        />

        {/* Route controls */}
        <div className="absolute top-3 left-3 z-10 flex flex-col gap-2">
          {routeState.step === 'idle' ? (
            <button
              id="start-route-btn"
              onClick={startRouteSelection}
              className="flex items-center gap-2 px-4 py-2.5 bg-accent hover:bg-accent/80 rounded-xl
                         text-sm font-semibold text-white transition-all shadow-lg shadow-accent/30"
            >
              <Navigation className="w-4 h-4" />
              Plan Safe Route
            </button>
          ) : (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-surface-card/95 border border-accent/30 rounded-xl backdrop-blur-sm">
              <MousePointer2 className="w-4 h-4 text-accent animate-pulse" />
              <span className="text-sm text-accent font-medium">{hint}</span>
              <button onClick={clearRoute} className="ml-2 text-muted hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        {/* Route result */}
        {routeResult && (
          <div className="absolute top-3 right-3 z-10">
            <RouteResultCard result={routeResult} onClear={clearRoute} />
          </div>
        )}

        {/* Instruction overlay */}
        {!routeResult && routeState.step === 'idle' && (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
            <div className="glass-card px-6 py-4 text-center max-w-sm">
              <Shield className="w-8 h-8 text-green-400 mx-auto mb-2" />
              <h2 className="text-sm font-semibold text-white mb-1">Flood-Safe Route Planner</h2>
              <p className="text-xs text-muted">
                Click &ldquo;Plan Safe Route&rdquo; then select start and end points on the Chennai map.
                The system will compute a route that avoids flooded streets.
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
