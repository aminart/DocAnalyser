import nightNavy from 'night-navy/tailwind-v3-preset';

/**
 * Couleurs, police et arrondis : design system commun Night Navy (github:aminart/Design-system-), le même
 * que SpecGen et Audit ergonomique. Classes : bg-bg, bg-surface, bg-surface-2/3, border-line, text-ink,
 * text-ink-muted, text-accent (liens, sélection), bg-primary (bouton principal), success / warning / danger.
 * Couleurs métier (palette des thèmes, types de fichiers) : src/theme.css.
 */
/** @type {import('tailwindcss').Config} */
export default {
  presets: [nightNavy],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  plugins: [],
};
