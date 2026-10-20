import { Analysis, AnalysisLevel, AnalysisMode, ModelInfo, UploadedDocument } from './types';

const API_BASE = (import.meta.env.VITE_ANALYSIS_API_URL || 'http://localhost:8000/api/v2').replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new Error('Serveur injoignable : vérifiez que le backend tourne sur le port 8000.');
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

  cancelAnalysis: (id: string) => request<Analysis>(`/analyses/${id}`, { method: 'DELETE' }),

  exportUrl: (id: string, format: 'md' | 'docx' | 'pdf') => `${API_BASE}/analyses/${id}/export?format=${format}`,
};
