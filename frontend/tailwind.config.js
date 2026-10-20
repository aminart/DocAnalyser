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
      },
    },
  },
  plugins: [],
};
