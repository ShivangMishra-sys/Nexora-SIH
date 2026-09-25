'use client';

import { useRef, useCallback } from 'react';
import type { IntensityPoint } from '@/types/flood';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface TimelineScrubberProps {
  currentTime: number;        // current sim minutes (0–180)
  maxTime?: number;
  onSeek: (t: number) => void;
  isPlaying: boolean;
  onPlayPause: () => void;
  intensityData: IntensityPoint[];
}

function formatTime(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.floor(minutes % 60);
  return `${h > 0 ? `+${h}h ` : '+'}${m.toString().padStart(2, '0')}min`;
}

export default function TimelineScrubber({
  currentTime,
  maxTime = 180,
  onSeek,
  isPlaying,
  onPlayPause,
  intensityData,
}: TimelineScrubberProps) {
  const sliderRef = useRef<HTMLInputElement>(null);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onSeek(Number(e.target.value));
    },
    [onSeek],
  );

  return (
    <div className="absolute bottom-0 left-0 right-0 z-10 bg-navy-50/95 backdrop-blur-sm border-t border-surface-border px-4 py-2">
      {/* Sparkline */}
      <div className="h-10 mb-1">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={intensityData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="t_minutes" hide />
            <YAxis hide domain={[0, 'auto']} />
            <Tooltip
              contentStyle={{ background: '#1a2236', border: '1px solid #2a3a58', borderRadius: 6, fontSize: 11 }}
              labelFormatter={(v) => `T+${v}min`}
              formatter={(v: number) => [`${v.toFixed(1)} mm/hr`, 'Peak']}
            />
            <Area
              type="monotone"
              dataKey="max_mm_hr"
              stroke="#3b82f6"
              strokeWidth={1.5}
              fill="url(#sparkGrad)"
              dot={false}
              isAnimationActive={false}
            />
            {/* Current time indicator line */}
            {intensityData.length > 0 && (
              <line
                x1={`${(currentTime / maxTime) * 100}%`}
                x2={`${(currentTime / maxTime) * 100}%`}
                y1="0"
                y2="100%"
                stroke="#f59e0b"
                strokeWidth={1}
                strokeDasharray="2 2"
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Controls row */}
      <div className="flex items-center gap-3">
        {/* Play/Pause */}
        <button
          id="timeline-play-pause"
          onClick={onPlayPause}
          className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full bg-accent hover:bg-accent/80 transition-colors"
          title={isPlaying ? 'Pause simulation' : 'Resume simulation'}
        >
          {isPlaying ? (
            <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5,3 19,12 5,21" />
            </svg>
          )}
        </button>

        {/* Time label */}
        <span className="flex-shrink-0 font-mono text-xs text-accent w-20 text-right">
          {formatTime(currentTime)}
        </span>

        {/* Slider */}
        <div className="relative flex-1">
          <input
            ref={sliderRef}
            id="timeline-slider"
            type="range"
            min={0}
            max={maxTime}
            step={5}
            value={currentTime}
            onChange={handleChange}
            className="timeline-slider w-full"
          />
          {/* Tick marks at 30-min intervals */}
          <div className="flex justify-between mt-0.5 px-0">
            {[0, 30, 60, 90, 120, 150, 180].map((t) => (
              <span key={t} className="text-[9px] text-muted/50 font-mono">
                {t === 0 ? 'Now' : `+${t}m`}
              </span>
            ))}
          </div>
        </div>

        {/* End label */}
        <span className="flex-shrink-0 font-mono text-xs text-muted">+3hr</span>
      </div>

      <style jsx>{`
        .timeline-slider {
          -webkit-appearance: none;
          appearance: none;
          height: 4px;
          background: linear-gradient(
            to right,
            #3b82f6 0%,
            #3b82f6 ${(currentTime / maxTime) * 100}%,
            #2a3a58 ${(currentTime / maxTime) * 100}%,
            #2a3a58 100%
          );
          border-radius: 2px;
          outline: none;
          cursor: pointer;
        }
        .timeline-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 14px; height: 14px;
          border-radius: 50%;
          background: #f59e0b;
          border: 2px solid #0a0f1e;
          box-shadow: 0 0 8px rgba(245,158,11,0.6);
          cursor: grab;
          transition: box-shadow 0.2s;
        }
        .timeline-slider::-webkit-slider-thumb:active { cursor: grabbing; }
        .timeline-slider::-moz-range-thumb {
          width: 14px; height: 14px;
          border-radius: 50%;
          background: #f59e0b;
          border: 2px solid #0a0f1e;
          cursor: grab;
        }
      `}</style>
    </div>
  );
}
