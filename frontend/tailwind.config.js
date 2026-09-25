/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Dark command-center palette
        navy:   { DEFAULT: '#0a0f1e', 50: '#1a2540', 100: '#151e35', 200: '#0f1729' },
        surface: { DEFAULT: '#111827', card: '#1a2236', elevated: '#1f2d44', border: '#2a3a58' },
        // Flood risk accent system
        flood: {
          dry:        '#64748b',   // neutral gray-blue
          nuisance:   '#f59e0b',   // amber
          disruptive: '#f97316',   // orange
          severe:     '#ef4444',   // red
          storm:      '#8b5cf6',   // purple (storm center)
        },
        // UI accents
        accent: { DEFAULT: '#3b82f6', glow: '#1d4ed8' },
        muted: '#94a3b8',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow':    'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-ring':    'pulse-ring 2s ease-out infinite',
        'slide-up':      'slide-up 0.3s ease-out',
        'fade-in':       'fade-in 0.2s ease-out',
        'glow':          'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        'pulse-ring': {
          '0%':   { transform: 'scale(1)', opacity: '1' },
          '100%': { transform: 'scale(2.5)', opacity: '0' },
        },
        'slide-up': {
          '0%':   { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'glow': {
          '0%':   { boxShadow: '0 0 5px rgba(59,130,246,0.3)' },
          '100%': { boxShadow: '0 0 20px rgba(59,130,246,0.8)' },
        },
      },
      backdropBlur: { xs: '2px' },
      boxShadow: {
        'glow-sm': '0 0 10px rgba(59,130,246,0.3)',
        'glow-md': '0 0 20px rgba(59,130,246,0.4)',
        'flood-severe': '0 0 15px rgba(239,68,68,0.5)',
      },
    },
  },
  plugins: [],
};
