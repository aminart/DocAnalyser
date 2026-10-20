/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Schibsted Grotesk"', 'system-ui', 'sans-serif'],
        serif: ['Newsreader', 'Georgia', 'serif'],
      },
      colors: {
        /* 0. Interface « Analyse documentaire » */
        ink: 'var(--ad-ink)',
        page: 'var(--ad-page)',
        line: 'var(--ad-line)',
        'line-strong': 'var(--ad-line-strong)',
        hair: 'var(--ad-hair)',
        muted: 'var(--ad-muted)',
        body: 'var(--ad-body)',
        prose: 'var(--ad-prose)',
        chip: 'var(--ad-chip)',
        'chip-ink': 'var(--ad-chip-ink)',
        accent: {
          DEFAULT: 'var(--ad-accent)',
          hover: 'var(--ad-accent-hover)',
          soft: 'var(--ad-accent-soft)',
          tint: 'var(--ad-accent-tint)',
          ink: 'var(--ad-accent-ink)',
        },
        ok: { DEFAULT: 'var(--ad-ok)', soft: 'var(--ad-ok-soft)' },
        /* 1. Brand / Identité visuelle (Signature DocIntel Studio) */
        brand: {
          50: 'var(--color-brand-50, #eef2ff)',
          100: 'var(--color-brand-100, #e0e7ff)',
          200: 'var(--color-brand-200, #c7d2fe)',
          300: 'var(--color-brand-300, #a5b4fc)',
          400: 'var(--color-brand-400, #818cf8)',
          500: 'var(--color-brand-500, #6366f1)',
          600: 'var(--color-brand-600, #4f46e5)',
          700: 'var(--color-brand-700, #4338ca)',
          800: 'var(--color-brand-800, #3730a3)',
          900: 'var(--color-brand-900, #312e81)',
        },
        /* 2. Surface / Neutres (Fonds, bordures, typographies) */
        surface: {
          50: 'var(--color-surface-50, #f8fafc)',
          100: 'var(--color-surface-100, #f1f5f9)',
          200: 'var(--color-surface-200, #e2e8f0)',
          300: 'var(--color-surface-300, #cbd5e1)',
          400: 'var(--color-surface-400, #94a3b8)',
          500: 'var(--color-surface-500, #64748b)',
          600: 'var(--color-surface-600, #475569)',
          700: 'var(--color-surface-700, #334155)',
          800: 'var(--color-surface-800, #1e293b)',
          900: 'var(--color-surface-900, #0f172a)',
        },
        /* 3. Succès (Décisions, barres complétées, validation) */
        success: {
          50: 'var(--color-success-50, #ecfdf5)',
          100: 'var(--color-success-100, #d1fae5)',
          200: 'var(--color-success-200, #a7f3d0)',
          500: 'var(--color-success-500, #10b981)',
          600: 'var(--color-success-600, #059669)',
          700: 'var(--color-success-700, #047857)',
          900: 'var(--color-success-900, #064e3b)',
          950: 'var(--color-success-950, #022c22)',
        },
        /* 4. Attention / Avertissement (Tensions, alertes, badges) */
        warning: {
          50: 'var(--color-warning-50, #fffbeb)',
          100: 'var(--color-warning-100, #fef3c7)',
          200: 'var(--color-warning-200, #fde68a)',
          500: 'var(--color-warning-500, #f59e0b)',
          600: 'var(--color-warning-600, #d97706)',
          700: 'var(--color-warning-700, #b45309)',
          800: 'var(--color-warning-800, #92400e)',
          950: 'var(--color-warning-950, #451a03)',
        },
        /* 5. Danger / Erreur (Suppression, blocage, échec) */
        danger: {
          50: 'var(--color-danger-50, #fff1f2)',
          100: 'var(--color-danger-100, #ffe4e6)',
          200: 'var(--color-danger-200, #fecdd3)',
          500: 'var(--color-danger-500, #f43f5e)',
          600: 'var(--color-danger-600, #e11d48)',
          700: 'var(--color-danger-700, #be123c)',
          800: 'var(--color-danger-800, #9f1239)',
          900: 'var(--color-danger-900, #881337)',
        },
        /* 6. Info (Tags fournisseurs, notes techniques) */
        info: {
          50: 'var(--color-info-50, #eff6ff)',
          100: 'var(--color-info-100, #dbeafe)',
          200: 'var(--color-info-200, #bfdbfe)',
          600: 'var(--color-info-600, #2563eb)',
          800: 'var(--color-info-800, #1e40af)',
        },
      },
    },
  },
  plugins: [],
};
