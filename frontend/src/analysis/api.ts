import {
  Analysis, AnalysisLevel, AnalysisSummary, AnalysisMode, ConnectionForm, ConnectionsState, ConnectionTest, ModelInfo,
  SourcePassage, SourceRequest, UploadedDocument,
} from './types';

// Même origine : le backend sert l'interface (et Vite relaie /api en développement, voir vite.config.ts).
const API_BASE = (import.meta.env.VITE_ANALYSIS_API_URL || '/api/v2').replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new Error('Serveur injoignable : l’application est-elle toujours lancée ? Relancez start.bat si besoin.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Erreur HTTP ${res.status}`);
  return data as T;
}

export const analysisApi = {
  listModels: () => request<ModelInfo[]>('/models'),

  uploadDocument(file: File): Promise<UploadedDocument> {
    const form = new FormData();
    form.append('file', file);
    return request<UploadedDocument>('/documents', { method: 'POST', body: form });
  },

  deleteDocument(id: string): void {
    fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' }).catch(() => undefined);
  },

  createAnalysis(params: {
    document_ids: string[];
    mode: AnalysisMode;
    level: AnalysisLevel;
    model_id: string;
    language: 'fr' | 'en';
    cite: boolean;
  }): Promise<Analysis> {
    return request<Analysis>('/analyses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
  },

  getAnalysis: (id: string) => request<Analysis>(`/analyses/${id}`),

  cancelAnalysis: (id: string) => request<Analysis>(`/analyses/${id}/cancel`, { method: 'POST' }),

  listAnalyses: () => request<AnalysisSummary[]>('/analyses'),

  async deleteAnalysis(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/analyses/${id}`, { method: 'DELETE' }).catch(() => null);
    if (!res || !res.ok) throw new Error('Impossible de supprimer cette analyse.');
  },

  getSource: (id: string, req: SourceRequest) =>
    request<SourcePassage>(`/analyses/${id}/source?${new URLSearchParams({ ...req })}`),

  exportUrl: (id: string, format: 'md' | 'docx' | 'pdf') => `${API_BASE}/analyses/${id}/export?format=${format}`,
};

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/** Écran Réglages : connexions aux modèles. */
export const connectionsApi = {
  list: () => request<ConnectionsState>('/connections'),
  create: (form: ConnectionForm & { last_test?: ConnectionTest }) => request<ConnectionsState>('/connections', json('POST', form)),
  update: (id: string, form: ConnectionForm & { last_test?: ConnectionTest }) => request<ConnectionsState>(`/connections/${id}`, json('PUT', form)),
  remove: (id: string) => request<ConnectionsState>(`/connections/${id}`, { method: 'DELETE' }),
  uploadCertificate(id: string, file: File): Promise<ConnectionsState> {
    const body = new FormData();
    body.append('file', file);
    return request<ConnectionsState>(`/connections/${id}/certificate`, { method: 'POST', body });
  },
  removeCertificate: (id: string) => request<ConnectionsState>(`/connections/${id}/certificate`, { method: 'DELETE' }),
  test: (form: ConnectionForm & { id?: string; certificate_b64?: string }) =>
    request<ConnectionTest>('/connections/test', json('POST', form)),
};

/** Prévient l'écran de configuration que la liste des modèles a changé. */
export const MODELS_CHANGED = 'docanalyser:models-changed';

