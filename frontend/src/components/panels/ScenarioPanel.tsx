'use client';

import type { ScenarioInfo, SimStatus } from '@/types/flood';
import { Activity, ChevronDown, Zap, Cloud, CloudRain } from 'lucide-react';

interface ScenarioPanelProps {
  scenarios: ScenarioInfo[];
  activeScenario: string;
  isPlaying: boolean;
  isLoading: boolean;
  connected: boolean;
  simClock: number;
  onSelectScenario: (name: string) => void;
}

const SCENARIO_ICONS: Record<string, React.ReactNode> = {
  cloudburst_extreme: <Zap className="w-3.5 h-3.5 text-red-400" />,
  moderate_steady:    <Cloud className="w-3.5 h-3.5 text-blue-400" />,
  heavy_localized:    <CloudRain className="w-3.5 h-3.5 text-orange-400" />,
};

const SCENARIO_BADGE: Record<string, string> = {
  cloudburst_extreme: 'bg-red-500/20 text-red-400 border-red-500/30',
  moderate_steady:    'bg-blue-500/20 text-blue-400 border-blue-500/30',
  heavy_localized:    'bg-orange-500/20 text-orange-400 border-orange-500/30',
};

export default function ScenarioPanel({
  scenarios,
  activeScenario,
  isPlaying,
  isLoading,
  connected,
  simClock,
  onSelectScenario,
}: ScenarioPanelProps) {
  const activeInfo = scenarios.find((s) => s.name === activeScenario);

  return (
    <div className="flex items-center gap-3">
      {/* Scenario selector */}
      <div className="relative">
        <select
          id="scenario-selector"
          value={activeScenario}
          onChange={(e) => onSelectScenario(e.target.value)}
          disabled={isLoading}
          className="appearance-none bg-surface-card border border-surface-border rounded-lg pl-3 pr-8 py-1.5
                     text-sm text-white font-medium cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent
                     hover:border-accent/50 transition-colors disabled:opacity-50"
        >
          {scenarios.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name === 'cloudburst_extreme' ? '⛈ Cloudburst Extreme' :
               s.name === 'moderate_steady'    ? '🌧 Moderate Steady' :
               s.name === 'heavy_localized'    ? '⛅ Heavy Localized' :
               s.name}
            </option>
          ))}
        </select>
        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted pointer-events-none" />
      </div>

      {/* Active scenario badge */}
      {activeInfo && (
        <div className={`flex items-center gap-1 px-2 py-1 rounded border text-xs font-medium ${SCENARIO_BADGE[activeScenario] ?? 'bg-gray-500/20 text-gray-400 border-gray-500/30'}`}>
          {SCENARIO_ICONS[activeScenario]}
          <span>{activeInfo.peak_intensity_mm_hr} mm/hr peak</span>
        </div>
      )}

      {/* Sim clock */}
      <div className="flex items-center gap-1.5 font-mono text-xs text-muted">
        <Activity className={`w-3 h-3 ${isPlaying ? 'text-green-400 animate-pulse' : 'text-muted'}`} />
        <span className="text-accent font-semibold">T+{Math.round(simClock)}min</span>
      </div>

      {/* WS connection indicator */}
      <div className={`flex items-center gap-1 text-xs ${connected ? 'text-green-400' : 'text-red-400'}`}>
        <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
        <span className="hidden sm:inline">{connected ? 'Live' : 'Offline'}</span>
      </div>
    </div>
  );
}
