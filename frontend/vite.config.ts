/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En production, le backend sert l'interface compilée (frontend/dist) sur http://127.0.0.1:8020.
// En développement (npm run dev), Vite relaie l'API vers ce même backend : python backend/launcher.py --no-browser --reload
const BACKEND = 'http://127.0.0.1:8020';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': BACKEND, '/health': BACKEND },
  },
  // Tests de l'interface (npm test) : composants rendus dans jsdom, API simulée. Les tests de bout en bout sont dans e2e/.
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
});
