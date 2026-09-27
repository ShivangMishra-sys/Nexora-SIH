'use client';

import { useState, useCallback, useEffect } from 'react';
import { api } from '@/lib/api';
import type { MapPin, RouteSelectionState } from '@/types/flood';

interface UseMapInteractionOptions {
  vehicleClass?: string;
}

interface UseMapInteractionResult {
  routeState: RouteSelectionState;
  hoveredNodeId: string | null;
  startRouteSelection: () => void;
  handleMapClick: (lat: number, lon: number) => void;
  clearRoute: () => void;
  setHoveredNodeId: (id: string | null) => void;
  setPresetRoute: (start: [number, number], end: [number, number]) => Promise<void>;
}

/**
 * Manages the click-to-route interaction and hovered node state.
 *
 * Route selection flow:
 *   idle → selecting_start → [click] → selecting_end → [click] → computing → done
 */
export function useMapInteraction({ vehicleClass = 'car' }: UseMapInteractionOptions = {}): UseMapInteractionResult {
  const [routeState, setRouteState] = useState<RouteSelectionState>({ step: 'idle' });
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Automatically recalculate route if vehicle class changes while route is active
  useEffect(() => {
    if (routeState.step === 'done' && routeState.start && routeState.end) {
      const { start, end } = routeState;
      api.computeRoute(
        [start.lat, start.lon],
        [end.lat, end.lon],
        vehicleClass,
      ).then(result => {
        setRouteState({ step: 'done', start, end, result });
      }).catch(err => {
        console.error('Failed to recompute route for vehicle class:', err);
      });
    }
  }, [vehicleClass]);

  const startRouteSelection = useCallback(() => {
    setRouteState({ step: 'selecting_start' });
  }, []);

  const handleMapClick = useCallback(
    async (lat: number, lon: number) => {
      if (routeState.step === 'selecting_start') {
        setRouteState({ step: 'selecting_end', start: { lat, lon } });
      } else if (routeState.step === 'selecting_end') {
        const { start } = routeState;
        setRouteState({ step: 'computing', start, end: { lat, lon } });

        try {
          const result = await api.computeRoute(
            [start.lat, start.lon],
            [lat, lon],
            vehicleClass,
          );
          setRouteState({ step: 'done', start, end: { lat, lon }, result });
        } catch (e) {
          console.error('Route computation failed:', e);
          setRouteState({ step: 'idle' });
        }
      }
    },
    [routeState, vehicleClass],
  );

  const setPresetRoute = useCallback(
    async (start: [number, number], end: [number, number]) => {
      setRouteState({
        step: 'computing',
        start: { lat: start[0], lon: start[1] },
        end: { lat: end[0], lon: end[1] },
      });
      try {
        const result = await api.computeRoute(start, end, vehicleClass);
        setRouteState({
          step: 'done',
          start: { lat: start[0], lon: start[1] },
          end: { lat: end[0], lon: end[1] },
          result,
        });
      } catch (e) {
        console.error('Preset route computation failed:', e);
        setRouteState({ step: 'idle' });
      }
    },
    [vehicleClass],
  );

  const clearRoute = useCallback(() => {
    setRouteState({ step: 'idle' });
  }, []);

  return {
    routeState,
    hoveredNodeId,
    startRouteSelection,
    handleMapClick,
    clearRoute,
    setHoveredNodeId,
    setPresetRoute,
  };
}
