import React, { useEffect, useRef, useState } from 'react';
import { analysisApi } from './api';
import { SourcePassage, SourceRequest } from './types';
import { FileBadge, Icons, extOf } from './ui';

/** Tiroir latéral : affiche le passage d'origine d'une source pour la vérifier sans quitter la synthèse. */
export const SourcePanel: React.FC<{
  analysisId: string;
  request: SourceRequest | null;
  onClose: () => void;
}> = ({ analysisId, request, onClose }) => {
  const [data, setData] = useState<SourcePassage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const firstHitRef = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (!request) return;
    let cancelled = false;
    setData(null);
    setError(null);
    closeRef.current?.focus();
    analysisApi
      .getSource(analysisId, request)
      .then((d) => !cancelled && setData(d))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [analysisId, request]);

  useEffect(() => {
    firstHitRef.current?.scrollIntoView({ block: 'center' });
  }, [data]);

  useEffect(() => {
    if (!request) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [request, onClose]);

  if (!request) return null;
  const docName = data?.document || request.document;
  let firstHitSeen = false;

  return (
    <div className="fixed inset-0 z-30 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="source-h">
      <button type="button" aria-label="Fermer" onClick={onClose} className="absolute inset-0 cursor-default border-none bg-[rgba(10,12,22,0.35)]" />
      <aside className="relative flex h-full w-full max-w-[520px] flex-col bg-surface shadow-2xl">
        <header className="flex items-start gap-3 border-b border-line px-6 py-5">
          <div className="flex min-w-0 flex-grow flex-col gap-1">
            <span id="source-h" className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-body">
              Source
            </span>
            {docName ? (
              <span className="flex items-center gap-2 font-semibold">
                <FileBadge ext={extOf(docName)} size="sm" />
                <span className="truncate">{docName}</span>
                {request.location && <span className="shrink-0 text-sm font-normal text-ink-muted">{request.location}</span>}
              </span>
            ) : (
              <span className="text-sm text-ink-muted">Recherche dans les documents…</span>
            )}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Fermer le panneau"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-ink-muted hover:bg-bg"
          >
            <Icons.close size={18} />
          </button>
        </header>

        <div className="flex flex-col gap-1.5 border-b border-line bg-bg px-6 py-4">
          <span className="text-xs font-semibold text-ink-body">Propos à vérifier</span>
          <p className="m-0 line-clamp-4 text-[15px] leading-normal text-ink-body">{request.text}</p>
        </div>

        <div className="flex-grow overflow-y-auto px-6 py-4">
          {error && (
            <p role="alert" className="m-0 text-sm text-danger-text">
              {error}
            </p>
          )}
          {!data && !error && <div className="ad-shimmer h-40 rounded-lg" aria-label="Chargement du passage" />}
          {data && !data.found && data.nearest && !request.location && (
            <p className="m-0 mb-3 text-[13px] text-ink-muted">Passage du document où figure ce propos :</p>
          )}
          {data && !data.found && (data.nearest ? !!request.location : true) && (
            <p className="m-0 mb-3 rounded-lg bg-warning-soft px-3 py-2 text-[13px] text-warning-text">
              {data.nearest
                ? `Le repère « ${request.location} » n'existe pas dans ce document : voici le passage le plus proche du propos.`
                : 'Aucun passage correspondant n’a été trouvé dans les documents. Ce point est à vérifier.'}
            </p>
          )}
          {data && data.lines.length > 0 && (
            <ol className="m-0 flex list-none flex-col p-0">
              {data.lines.map((l, i) => {
                const isFirst = l.hit && !firstHitSeen;
                if (l.hit) firstHitSeen = true;
                return (
                  <li
                    key={i}
                    ref={isFirst ? firstHitRef : undefined}
                    className={`grid grid-cols-[76px_1fr] gap-3 border-l-[3px] py-1 pl-2 text-[14px] leading-normal ${
                      l.hit ? 'border-accent bg-[var(--ad-surlignage)] text-ink' : 'border-transparent text-ink-muted'
                    }`}
                  >
                    <span className="pt-px font-mono text-[11px] text-ink-muted">{l.ref}</span>
                    <span className="whitespace-pre-wrap break-words">{l.text}</span>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </aside>
    </div>
  );
};
