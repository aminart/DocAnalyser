import {
  DocumentMetadata,
  DocumentPreviewResponse,
  ExportFormat,
  JobStatusResponse,
  ModelOption,
  SynthesisMode,
} from '../types/synthesis';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
const DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024; // 5 Mo par chunk

export const synthesisApi = {
  async getAvailableModels(): Promise<ModelOption[]> {
    const res = await fetch(`${API_BASE}/models`);
    if (!res.ok) throw new Error('Impossible de charger la liste des modèles LLM.');
    return res.json();
  },

  async uploadLargeFile(
    file: File,
    onChunkProgress: (uploadedBytes: number, totalBytes: number) => void
  ): Promise<DocumentMetadata> {
    const totalChunks = Math.max(1, Math.ceil(file.size / DEFAULT_CHUNK_SIZE));

    const initRes = await fetch(`${API_BASE}/uploads/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_name: file.name,
        mime_type: file.type || 'application/octet-stream',
        total_size_bytes: file.size,
        total_chunks: totalChunks,
      }),
    });

    if (!initRes.ok) {
      throw new Error(`Erreur d'initialisation de l'upload pour ${file.name}`);
    }

    const { document_id, chunk_size_bytes } = await initRes.json();
    let lastMeta: DocumentMetadata | null = null;

    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
      const start = chunkIndex * chunk_size_bytes;
      const end = Math.min(file.size, start + chunk_size_bytes);
      const blobSlice = file.slice(start, end);

      const formData = new FormData();
      formData.append('chunk_index', String(chunkIndex));
      formData.append('chunk', blobSlice, file.name);

      const chunkRes = await fetch(`${API_BASE}/uploads/${document_id}/chunk`, {
        method: 'POST',
        body: formData,
      });

      if (!chunkRes.ok) {
        throw new Error(`Échec de l'envoi du segment ${chunkIndex + 1}/${totalChunks} pour ${file.name}`);
      }

      lastMeta = await chunkRes.json();
      onChunkProgress(end, file.size);
    }

    if (!lastMeta) {
      throw new Error('Métadonnées du document manquantes après upload.');
    }
    return lastMeta;
  },

  async startSynthesisJob(params: {
    documentIds: string[];
    mode: SynthesisMode;
    modelName: string;
  }): Promise<JobStatusResponse> {
    const res = await fetch(`${API_BASE}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_ids: params.documentIds,
        mode: params.mode,
        model_name: params.modelName,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Impossible de démarrer le job de synthèse.');
    }
    return res.json();
  },

  async fetchJobStatus(jobId: string): Promise<JobStatusResponse> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}`);
    if (!res.ok) throw new Error('Erreur lors de la récupération du statut du job.');
    return res.json();
  },

  async fetchDocumentBlocks(documentId: string): Promise<DocumentPreviewResponse> {
    const res = await fetch(`${API_BASE}/documents/${documentId}/blocks`);
    if (!res.ok) throw new Error('Impossible de charger les segments du document.');
    return res.json();
  },

  getExportUrl(jobId: string, format: ExportFormat): string {
    return `${API_BASE}/jobs/${jobId}/export?format=${format}`;
  },
};
