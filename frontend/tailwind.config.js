/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      /* ── Color System ─────────────────────────────────── */
      colors: {
        // Core Surfaces & Text (CSS Variable driven)
        background: {
          DEFAULT: 'var(--background)',
          secondary: 'var(--background-secondary)',
        },
        surface: {
          DEFAULT: 'var(--surface)',
          raised: 'var(--surface-raised)',
          overlay: 'var(--surface-overlay)',
        },
        foreground: {
          DEFAULT: 'var(--foreground)',
          secondary: 'var(--foreground-secondary)',
          muted: 'var(--foreground-muted)',
        },
        border: {
          DEFAULT: 'var(--border)',
          strong: 'var(--border-strong)',
          focus: 'var(--border-focus)',
        },

        // Agent State Semantic Accents
        accent: {
          planner:  'var(--accent-planner)',
          executor: 'var(--accent-executor)',
          verifier: 'var(--accent-verifier)',
          error:    'var(--accent-error)',
          primary:  'var(--accent-primary)',
          'primary-hover': 'var(--accent-primary-hover)',
        },

        // FPT Brand
        brand: {
          primary: 'var(--brand-primary)',
          accent:  'var(--brand-accent)',
          50: '#f0f7ff',
          100: '#e0effe',
          500: '#005697',
          600: '#004880',
          700: '#005697',
          800: '#003e6d',
          900: '#002949',
        },

        // Legacy FPT compat
        fpt: {
          blue: '#005697',
          orange: '#F37021',
          green: '#10B981',
        },
      },

      /* ── Font Family ─────────────────────────────────── */
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'ui-monospace', 'monospace'],
      },

      /* ── Spacing (8pt Grid Extensions) ──────────────── */
      spacing: {
        '4.5': '18px',
        '13': '52px',
        '15': '60px',
        '18': '72px',
        '22': '88px',
      },

      /* ── Border Radius ──────────────────────────────── */
      borderRadius: {
        'sm': '6px',
        'DEFAULT': '8px',
        'lg': '12px',
        'xl': '16px',
        '2xl': '20px',
        '3xl': '24px',
      },

      /* ── Box Shadow ─────────────────────────────────── */
      boxShadow: {
        'xs': 'var(--shadow-sm)',
        'enterprise': 'var(--shadow-md)',
        'glow-blue': 'var(--shadow-glow-blue)',
        'glow-amber': 'var(--shadow-glow-amber)',
        'glow-emerald': 'var(--shadow-glow-emerald)',
      },

      /* ── Animations ─────────────────────────────────── */
      animation: {
        'shimmer': 'shimmer 1.5s ease-in-out infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'pulse-glow-amber': 'pulse-glow-amber 2s ease-in-out infinite',
        'pulse-glow-emerald': 'pulse-glow-emerald 2s ease-in-out infinite',
        'fade-in': 'fade-in 200ms ease-out both',
        'fade-in-scale': 'fade-in-scale 200ms ease-out both',
        'accordion-down': 'accordion-down 300ms ease-out both',
        'accordion-up': 'accordion-up 200ms ease-out both',
        'typing-dot': 'typing-dot 1.2s ease-in-out infinite',
      },

      /* ── Keyframes ──────────────────────────────────── */
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(59, 130, 246, 0.3)' },
          '50%': { boxShadow: '0 0 0 6px rgba(59, 130, 246, 0)' },
        },
        'pulse-glow-amber': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(245, 158, 11, 0.3)' },
          '50%': { boxShadow: '0 0 0 6px rgba(245, 158, 11, 0)' },
        },
        'pulse-glow-emerald': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(16, 185, 129, 0.3)' },
          '50%': { boxShadow: '0 0 0 6px rgba(16, 185, 129, 0)' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in-scale': {
          from: { opacity: '0', transform: 'scale(0.96)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        'accordion-down': {
          from: { maxHeight: '0', opacity: '0' },
          to: { maxHeight: '500px', opacity: '1' },
        },
        'accordion-up': {
          from: { maxHeight: '500px', opacity: '1' },
          to: { maxHeight: '0', opacity: '0' },
        },
        'typing-dot': {
          '0%, 60%, 100%': { transform: 'translateY(0)', opacity: '0.4' },
          '30%': { transform: 'translateY(-4px)', opacity: '1' },
        },
      },

      /* ── Transition ─────────────────────────────────── */
      transitionDuration: {
        '150': '150ms',
        '200': '200ms',
        '300': '300ms',
      },
      transitionTimingFunction: {
        'out': 'ease-out',
        'in-out': 'ease-in-out',
      },

      /* ── Grid (12-col Dashboard) ────────────────────── */
      gridTemplateColumns: {
        'dashboard': 'repeat(12, minmax(0, 1fr))',
      },
    },
  },
  plugins: [],
};
