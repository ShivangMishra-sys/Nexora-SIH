'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { api } from '@/lib/api';
import type { ScenarioInfo, SimStatus } from '@/types/flood';

interface UseSimulationResult {
  scenarios: ScenarioInfo[];
  status: SimStatus | null;
  activeScenario: string;
  isLoading: boolean;
  error: string | null;
  selectScenario: (name: string) => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  isPlaying: boolean;
}

/**
 * Manages scenario selection, play/pause state, and simulation status polling.
 */
export function useSimulation(): UseSimulationResult {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [status, setStatus] = useState<SimStatus | null>(null);
  const [activeScenario, setActiveScenario] = useState('cloudburst_extreme');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load scenario list once
  useEffect(() => {
    api.listScenarios()
      .then(setScenarios)
      .catch((e) => setError(String(e)));
  }, []);

  // Poll status every 3s for sim clock updates
  useEffect(() => {
    const poll = () => {
      api.getStatus()
        .then((s) => {
          setStatus(s);
          if (s.scenario) setActiveScenario(s.scenario);
          setIsPlaying(!s.is_paused && s.is_running);
        })
        .catch(() => {/* ignore polling errors */});
    };

    poll(); // immediate
    pollRef.current = setInterval(poll, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const selectScenario = useCallback(async (name: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await api.runScenario(name);
      setActiveScenario(name);
      setIsPlaying(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const pause = useCallback(async () => {
    await api.pause();
    setIsPlaying(false);
  }, []);

  const resume = useCallback(async () => {
    await api.resume();
    setIsPlaying(true);
  }, []);

  return {
    scenarios,
    status,
    activeScenario,
    isLoading,
    error,
    selectScenario,
    pause,
    resume,
    isPlaying,
  };
}
