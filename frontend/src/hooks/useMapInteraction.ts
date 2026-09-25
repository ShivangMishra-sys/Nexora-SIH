'use client';

import { useState, useCallback } from 'react';
import { api } from '@/lib/api';
import type { MapPin, RouteResult, RouteSelectionState } from '@/types/flood';

interface UseMapInteractionResult {
  routeState: RouteSelectionState;
  hoveredNodeId: string | null;
  startRouteSelection: () => void;
  handleMapClick: (lat: number, lon: number) => void;
  clearRoute: () => void;
  setHoveredNodeId: (id: string | null) => void;
}

/**
 * Manages the click-to-route interaction and hovered node state.
 *
 * Route selection flow:
 *   idle → selecting_start → [click] → selecting_end → [click] → computing → done
 */
export function useMapInteraction(): UseMapInteractionResult {
  const [routeState, setRouteState] = useState<RouteSelectionState>({ step: 'idle' });
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

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
          );
          setRouteState({ step: 'done', start, end: { lat, lon }, result });
        } catch (e) {
          console.error('Route computation failed:', e);
          setRouteState({ step: 'idle' });
        }
      }
    },
    [routeState],
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
  };
}
