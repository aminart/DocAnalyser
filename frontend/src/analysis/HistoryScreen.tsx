import React, { useEffect, useState } from 'react';
import { analysisApi } from './api';
import { AnalysisStatus, AnalysisSummary } from './types';
import { FileBadge, extOf } from './ui';

const STATUS: Record<AnalysisStatus, [string, string, string]> = {
  done: ['Terminée', 'var(--nn-success-soft)', 'var(--nn-success-text)'],
  running: ['En cours', 'var(--nn-accent-soft)', 'var(--nn-accent-ink)'],
  failed: ['Échouée', 'var(--nn-danger-soft)', 'var(--nn-danger-text)'],
  cancelled: ['Annulée', 'var(--nn-surface-3)', 'var(--nn-ink-muted)'],
};

const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

export const HistoryScreen: React.FC<{
  onOpen: (item: AnalysisSummary) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
}> = ({ onOpen, onNew, onDeleted }) => {
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = () =>
    analysisApi
      .listAnalyses()
      .then(setItems)
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const remove = async (id: string) => {
    try {
      await analysisApi.deleteAnalysis(id);
      setItems((prev) => prev?.filter((i) => i.id !== id) ?? null);
      onDeleted(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Suppression impossible.');
    } finally {
      setConfirming(null);
    }
  };

  return (
    <main className="mx-auto box-border max-w-[1240px] px-8 pb-[72px] pt-10">
      <div className="mb-8 flex flex-wrap items-end gap-4">
        <div className="flex flex-grow flex-col gap-1.5">
          <h1 className="nn-page-title">Historique</h1>
          <p className="m-0 text-base text-ink-muted">
            Vos analyses enregistrées. Supprimer une analyse efface aussi ses documents s’ils ne servent à aucune autre.
          </p>
        </div>
        <button
          type="button"
          onClick={onNew}
          className="inline-flex min-h-11 items-center rounded-[10px] border-none bg-primary px-4 font-semibold text-white hover:bg-primary-hover"
        >
          Nouvelle analyse
        </button>
      </div>

      {error && (
        <p role="alert" className="m-0 mb-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger-text">
          {error}
        </p>
      )}
      {!items && !error && <div className="ad-shimmer h-40 rounded-[14px]" aria-label="Chargement de l'historique" />}
      {items && items.length === 0 && (
        <div className="rounded-[14px] border border-dashed border-line-strong bg-surface px-6 py-12 text-center text-ink-muted">
          Aucune analyse pour l’instant.
        </div>
      )}

      {items && items.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {items.map((it) => {
            const [label, bg, fg] = STATUS[it.status];
            return (
              <li key={it.id} className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-[14px] border border-line bg-surface px-6 py-5">
                <button
                  type="button"
                  onClick={() => onOpen(it)}
                  className="flex min-w-0 flex-[999_1_420px] flex-col gap-2 border-none bg-transparent p-0 text-left text-ink"
                >
                  <span className="flex flex-wrap items-center gap-2.5">
                    <span className="text-[17px] font-bold hover:text-accent-ink">{it.title}</span>
                    <span className="rounded-full px-2.5 py-0.5 text-xs font-semibold" style={{ background: bg, color: fg }}>
                      {label}
                    </span>
                  </span>
                  <span className="text-[13px] text-ink-muted">
                    {formatDateTime(it.created_at)} · {it.mode_label} · {it.level_label} · {it.model_name}
                  </span>
                  <span className="flex flex-wrap gap-x-4 gap-y-1">
                    {it.documents.map((d) => (
                      <span key={d} className="inline-flex min-w-0 items-center gap-1.5 text-[13px] text-ink-body">
                        <FileBadge ext={extOf(d)} size="sm" />
                        <span className="max-w-[260px] truncate">{d}</span>
                      </span>
                    ))}
                  </span>
                </button>
                <div className="flex shrink-0 items-center gap-2">
                  {confirming === it.id ? (
                    <>
                      <span className="text-sm text-ink-body">Supprimer définitivement ?</span>
                      <button
                        type="button"
                        onClick={() => remove(it.id)}
                        className="min-h-9 rounded-lg border-none bg-[#9B2216] px-3 text-sm font-semibold text-white"
                      >
                        Supprimer
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirming(null)}
                        className="min-h-9 rounded-lg border border-line-strong bg-surface px-3 text-sm font-semibold text-ink"
                      >
                        Annuler
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => onOpen(it)}
                        className="min-h-9 rounded-lg border border-line-strong bg-surface px-3 text-sm font-semibold text-ink hover:bg-bg"
                      >
                        Ouvrir
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirming(it.id)}
                        aria-label={`Supprimer l'analyse ${it.title}`}
                        className="min-h-9 rounded-lg border border-line-strong bg-surface px-3 text-sm font-semibold text-danger-text hover:bg-danger-soft"
                      >
                        Supprimer
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
};
