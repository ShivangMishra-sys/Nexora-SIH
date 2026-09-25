'use client';

import React, { useEffect, useRef, useCallback, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { GeoJSONCollection, FloodNodePoint, RouteResult } from '@/lib/api';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
const ANNA_NAGAR_CENTER: [number, number] = [80.21, 13.10];
const ANNA_NAGAR_ZOOM = 13;

// Risk → MapLibre color expression
const RISK_COLOR_EXPR = [
  'match', ['get', 'risk'],
  'safe',       '#6b7280',
  'caution',    '#f59e0b',
  'critical',   '#f97316',
  'impassable', '#ef4444',
  '#6b7280',
] as unknown as maplibregl.ExpressionSpecification;

const DEPTH_WIDTH_EXPR = [
  'interpolate', ['linear'], ['get', 'depth_cm'],
  0, 1.5,
  15, 3.0,
  30, 5.5,
] as unknown as maplibregl.ExpressionSpecification;

interface FloodMapProps {
  networkGeoJSON: GeoJSONCollection | null;
  floodNodes: FloodNodePoint[];
  routeResult: RouteResult | null;
  routeState: RouteSelectionState;
  onMapClick: (lat: number, lon: number) => void;
  onNodeHover: (nodeId: string | null) => void;
}

export type RouteSelectionState =
  | { step: 'idle' }
  | { step: 'selecting_start' }
  | { step: 'selecting_end'; start: { lat: number; lon: number } }
  | { step: 'computing'; start: { lat: number; lon: number }; end: { lat: number; lon: number } }
  | { step: 'done'; start: { lat: number; lon: number }; end: { lat: number; lon: number }; result: RouteResult };

export default function FloodMap({
  networkGeoJSON,
  floodNodes,
  routeResult,
  routeState,
  onMapClick,
  onNodeHover,
}: FloodMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const startMarkerRef = useRef<maplibregl.Marker | null>(null);
  const endMarkerRef   = useRef<maplibregl.Marker | null>(null);
  const onMapClickRef  = useRef(onMapClick);
  const onNodeHoverRef = useRef(onNodeHover);

  useEffect(() => { onMapClickRef.current  = onMapClick;  }, [onMapClick]);
  useEffect(() => { onNodeHoverRef.current = onNodeHover; }, [onNodeHover]);

  // ── Initialise map ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: ANNA_NAGAR_CENTER,
      zoom: ANNA_NAGAR_ZOOM,
      antialias: true,
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

    map.on('load', () => {
      // Network edges layer
      map.addSource('network', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({
        id: 'network-edges',
        type: 'line',
        source: 'network',
        filter: ['==', ['geometry-type'], 'LineString'],
        paint: {
          'line-color': RISK_COLOR_EXPR,
          'line-width': DEPTH_WIDTH_EXPR,
          'line-opacity': 0.85,
        },
      });

      // Network nodes
      map.addLayer({
        id: 'network-nodes',
        type: 'circle',
        source: 'network',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'depth_cm'], 0, 3, 30, 9],
          'circle-color': RISK_COLOR_EXPR,
          'circle-opacity': 0.8,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 0.5,
        },
      });

      // Route layers
      map.addSource('route-safe',  { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addSource('route-naive', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'route-naive-line', type: 'line', source: 'route-naive',
        paint: { 'line-color': '#94a3b8', 'line-width': 4, 'line-dasharray': [3, 2] } });
      map.addLayer({ id: 'route-safe-line', type: 'line', source: 'route-safe',
        paint: { 'line-color': '#22c55e', 'line-width': 5, 'line-opacity': 0.95 } });

      // Map click
      map.on('click', (e) => {
        const { lat, lng } = e.lngLat;
        onMapClickRef.current(lat, lng);
      });

      // Node hover
      map.on('mousemove', 'network-nodes', (e) => {
        if (e.features?.length) {
          const f = e.features[0];
          onNodeHoverRef.current(f.properties?.node_id as string ?? null);
          map.getCanvas().style.cursor = 'pointer';
        }
      });
      map.on('mouseleave', 'network-nodes', () => {
        onNodeHoverRef.current(null);
        map.getCanvas().style.cursor = '';
      });

      mapRef.current = map;
      setMapReady(true);
    });

    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // ── Update network GeoJSON ─────────────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !mapRef.current || !networkGeoJSON) return;
    const src = mapRef.current.getSource('network') as maplibregl.GeoJSONSource;
    src?.setData(networkGeoJSON as unknown as GeoJSON.GeoJSON);
  }, [mapReady, networkGeoJSON]);

  // ── Update route lines ─────────────────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !mapRef.current || !routeResult) return;
    const map = mapRef.current;
    const toLine = (coords: { lat: number; lon: number }[]) => ({
      type: 'FeatureCollection' as const,
      features: [{ type: 'Feature' as const,
        geometry: { type: 'LineString' as const, coordinates: coords.map(c => [c.lon, c.lat]) },
        properties: {} }],
    });
    (map.getSource('route-safe') as maplibregl.GeoJSONSource)?.setData(toLine(routeResult.safe_route.coordinates));
    (map.getSource('route-naive') as maplibregl.GeoJSONSource)?.setData(toLine(routeResult.naive_route.coordinates));

    const allCoords = [...routeResult.safe_route.coordinates, ...routeResult.naive_route.coordinates];
    if (allCoords.length > 0) {
      const lons = allCoords.map(c => c.lon);
      const lats = allCoords.map(c => c.lat);
      map.fitBounds(
        [[Math.min(...lons) - 0.005, Math.min(...lats) - 0.005],
         [Math.max(...lons) + 0.005, Math.max(...lats) + 0.005]],
        { padding: 80, duration: 800 },
      );
    }
  }, [mapReady, routeResult]);

  // ── Start/End markers ─────────────────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const start = 'start' in routeState ? routeState.start : null;
    const end   = 'end'   in routeState ? routeState.end   : null;

    if (start) {
      if (!startMarkerRef.current)
        startMarkerRef.current = new maplibregl.Marker({ color: '#3b82f6' }).setLngLat([start.lon, start.lat]).addTo(map);
      else startMarkerRef.current.setLngLat([start.lon, start.lat]);
    } else { startMarkerRef.current?.remove(); startMarkerRef.current = null; }

    if (end) {
      if (!endMarkerRef.current)
        endMarkerRef.current = new maplibregl.Marker({ color: '#22c55e' }).setLngLat([end.lon, end.lat]).addTo(map);
      else endMarkerRef.current.setLngLat([end.lon, end.lat]);
    } else { endMarkerRef.current?.remove(); endMarkerRef.current = null; }
  }, [mapReady, routeState]);

  // ── Crosshair cursor during selection ─────────────────────────────────
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const canvas = mapRef.current.getCanvas();
    canvas.style.cursor =
      (routeState.step === 'selecting_start' || routeState.step === 'selecting_end')
        ? 'crosshair' : '';
  }, [mapReady, routeState.step]);

  return <div ref={containerRef} className="w-full h-full" />;
}
