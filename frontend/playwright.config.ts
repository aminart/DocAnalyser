import { defineConfig } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

// Tests de bout en bout (npm run e2e) : l'interface compilée (npm run build) servie par le vrai backend,
// branché sur un faux modèle compatible OpenAI, avec un historique de test préparé par e2e/seed.py.
const PYTHON = process.env.PYTHON ?? 'python3';
const PORT = 8031;
const LLM_PORT = 9911;
const DATA = path.join(os.tmpdir(), 'docanalyser-e2e');

const env = {
  STORAGE_DIR: path.join(DATA, 'donnees'),
  DOCANALYSER_CONFIG: path.join(DATA, 'config'),
  CUSTOM_LLM_PROVIDER_NAME: 'Faux modèle',
  CUSTOM_LLM_API_BASE: `http://127.0.0.1:${LLM_PORT}/v1`,
  CUSTOM_LLM_AVAILABLE_MODELS: 'fake-model',
  FAKE_LLM_PORT: String(LLM_PORT),
};

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'off' },
  webServer: [
    {
      command: `${PYTHON} e2e/fake_llm.py`,
      url: `http://127.0.0.1:${LLM_PORT}/v1/models`,
      env,
      reuseExistingServer: false,
    },
    {
      command: `${PYTHON} e2e/seed.py && ${PYTHON} ../backend/launcher.py --port ${PORT} --no-browser`,
      url: `http://127.0.0.1:${PORT}/health`,
      env,
      reuseExistingServer: false,
    },
  ],
});
