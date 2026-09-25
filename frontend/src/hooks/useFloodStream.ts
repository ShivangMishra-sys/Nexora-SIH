'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { createFloodWebSocket } from '@/lib/api';
import type { FloodState } from '@/types/flood';

interface UseFloodStreamOptions {
  enabled?: boolean;
  reconnectDelayMs?: number;
}

interface UseFloodStreamResult {
  state: FloodState | null;
  connected: boolean;
  lastUpdated: Date | null;
  tickCount: number;
}

/**
 * WebSocket hook that maintains a persistent connection to /ws/flood-stream.
 * Reconnects automatically with exponential backoff on disconnect.
 */
export function useFloodStream({
  enabled = true,
  reconnectDelayMs = 2000,
}: UseFloodStreamOptions = {}): UseFloodStreamResult {
  const [state, setState] = useState<FloodState | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [tickCount, setTickCount] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const retryDelayRef = useRef(reconnectDelayMs);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    const ws = createFloodWebSocket(
      (newState) => {
        setState(newState);
        setLastUpdated(new Date());
        setTickCount((c) => c + 1);
        retryDelayRef.current = reconnectDelayMs; // reset backoff on success
      },
      () => {
        // keepalive received — connection is healthy
      },
    );

    ws.onopen = () => {
      if (mountedRef.current) {
        setConnected(true);
      }
    };

    ws.onclose = () => {
      if (mountedRef.current) {
        setConnected(false);
        // Exponential backoff reconnect (cap at 30s)
        retryTimerRef.current = setTimeout(() => {
          retryDelayRef.current = Math.min(retryDelayRef.current * 1.5, 30_000);
          connect();
        }, retryDelayRef.current);
      }
    };

    wsRef.current = ws;
  }, [enabled, reconnectDelayMs]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { state, connected, lastUpdated, tickCount };
}
