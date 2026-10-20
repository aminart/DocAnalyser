import { useCallback, useEffect, useRef, useState } from 'react';
import { synthesisApi } from '../services/api';
import {
  DocumentMetadata,
  ExportFormat,
  JobStatusResponse,
  ModelOption,
  SynthesisMode,
} from '../types/synthesis';

export interface FileUploadState {
  file: File;
  progressPercent: number;
  status: 'pending' | 'uploading' | 'done' | 'error';
  metadata?: DocumentMetadata;
  error?: string;
}

export function useSynthesisJob() {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [filesState, setFilesState] = useState<FileUploadState[]>([]);
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
  const [selectedMode, setSelectedMode] = useState<SynthesisMode>('global_summary');
  const [selectedModel, setSelectedModel] = useState<string>('mistral-medium-latest');
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const pollingRef = useRef<number | null>(null);

  useEffect(() => {
    synthesisApi
      .getAvailableModels()
      .then((models) => {
        setAvailableModels(models);
        if (models.length > 0) {
          setSelectedModel(models[0].id);
        }
      })
      .catch(() => {
        setAvailableModels([
          {
            id: 'mistral-medium-latest',
            label: 'Mistral Medium (Équilibré - Recommandé)',
            description: 'Haute précision analytique pour rapports complexes, Excel denses et parcours UX.',
            context_window: 128000,
          },
          {
            id: 'mistral-small-latest',
            label: 'Mistral Small (Rapide & Économique)',
            description: 'Idéal pour les notes en vrac, transcriptions et synthèses rapides.',
            context_window: 32000,
          },
        ]);
      });
  }, []);

  const addFiles = useCallback(async (incomingFiles: File[]) => {
    setGlobalError(null);
    const newEntries: FileUploadState[] = incomingFiles.map((file) => ({
      file,
      progressPercent: 0,
      status: 'uploading',
    }));

    setFilesState((prev) => [...prev, ...newEntries]);

    await Promise.all(
      incomingFiles.map(async (file) => {
        try {
          const meta = await synthesisApi.uploadLargeFile(file, (uploaded, total) => {
            const pct = Math.round((uploaded / total) * 100);
            setFilesState((current) =>
              current.map((item) =>
                item.file === file ? { ...item, progressPercent: pct } : item
              )
            );
          });

          setFilesState((current) =>
            current.map((item) =>
              item.file === file
                ? { ...item, progressPercent: 100, status: 'done', metadata: meta }
                : item
            )
          );
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Erreur upload';
          setFilesState((current) =>
            current.map((item) =>
              item.file === file ? { ...item, status: 'error', error: message } : item
            )
          );
        }
      })
    );
  }, []);

  const removeFile = useCallback((targetFile: File) => {
    setFilesState((prev) => prev.filter((f) => f.file !== targetFile));
  }, []);

  const launchAnalysis = useCallback(async () => {
    const readyDocIds = filesState
      .filter((f) => f.status === 'done' && f.metadata)
      .map((f) => f.metadata!.document_id);

    if (readyDocIds.length === 0) {
      setGlobalError('Veuillez importer au moins un document complet avant de lancer la synthèse.');
      return;
    }

    try {
      setGlobalError(null);
      const createdJob = await synthesisApi.startSynthesisJob({
        documentIds: readyDocIds,
        mode: selectedMode,
        modelName: selectedModel,
      });
      setJob(createdJob);
      setStep(3);
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : 'Erreur au lancement du job.');
    }
  }, [filesState, selectedMode, selectedModel]);

  useEffect(() => {
    if (!job || job.stage === 'ready' || job.stage === 'failed') {
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
      return;
    }

    pollingRef.current = window.setInterval(async () => {
      try {
        const updated = await synthesisApi.fetchJobStatus(job.job_id);
        setJob(updated);
      } catch (err) {
        console.error('Polling error:', err);
      }
    }, 1000);

    return () => {
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current);
      }
    };
  }, [job]);

  const triggerExport = useCallback(
    (format: ExportFormat) => {
      if (!job) return;
      window.open(synthesisApi.getExportUrl(job.job_id, format), '_blank', 'noopener,noreferrer');
    },
    [job]
  );

  const resetWizard = useCallback(() => {
    setJob(null);
    setFilesState([]);
    setStep(1);
    setGlobalError(null);
  }, []);

  return {
    step,
    setStep,
    filesState,
    addFiles,
    removeFile,
    availableModels,
    selectedMode,
    setSelectedMode,
    selectedModel,
    setSelectedModel,
    job,
    globalError,
    launchAnalysis,
    triggerExport,
    resetWizard,
  };
}
