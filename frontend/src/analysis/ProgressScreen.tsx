import React from 'react';
import { Analysis } from './types';
import { Icons, docCountLabel, themeColor } from './ui';

const Spinner: React.FC<{ size: number; stroke: number }> = ({ size, stroke }) => (
  <svg className="ad-spin" width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
    <circle cx="32" cy="32" r="28" fill="none" stroke="var(--nn-line)" strokeWidth={stroke} />
    <path d="M32 4a28 28 0 0 1 28 28" fill="none" stroke="var(--nn-primary)" strokeWidth={stroke} strokeLinecap="round" />
  </svg>
);

export const ProgressScreen: React.FC<{
  analysis: Analysis;
  onCancel: () => void;
  onShowResult: () => void;
  onBack: () => void;
}> = ({ analysis, onCancel, onShowResult, onBack }) => {
  const running = analysis.status === 'running';
  const done = analysis.status === 'done';
  const pct = done ? 100 : analysis.progress;
  const active = analysis.steps.find((s) => s.state === 'active');
  const flow = analysis.mode === 'flow';
  const found = analysis.result
    ? analysis.result.kind === 'themes'
      ? analysis.result.themes.length
      : analysis.result.phases.length
    : analysis.preview.length;

  const nDocs = analysis.documents.length;
  const yourDocs = nDocs > 1 ? `vos ${docCountLabel(nDocs)}` : 'votre document';

  const headline = done
    ? 'Votre synthèse est prête'
    : analysis.status === 'failed'
      ? 'L’analyse a échoué'
      : analysis.status === 'cancelled'
        ? 'Analyse annulée'
        : 'Analyse en cours…';

  const subline = done
    ? flow
      ? `${found} étapes du parcours ont été reconstituées à partir de ${yourDocs}.`
      : `${found} grands thèmes ont été identifiés dans ${yourDocs}.`
    : analysis.status === 'failed'
      ? analysis.error
      : analysis.status === 'cancelled'
        ? 'Vous pouvez relancer une analyse depuis la configuration.'
        : active
          ? `${active.label} — vous pouvez quitter cette page, l’analyse continue en arrière-plan.`
          : '';

  return (
    <main className="mx-auto box-border flex max-w-[760px] flex-col gap-7 px-6 pb-20 pt-16">
      <div className="flex flex-col items-center gap-3.5 text-center">
        <div className="relative h-16 w-16">
          {running && <Spinner size={64} stroke={5} />}
          {done && (
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-primary text-white">
              <Icons.check size={30} strokeWidth={2.4} />
            </span>
          )}
          {!running && !done && (
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-danger-soft text-danger-text">
              <Icons.close size={28} strokeWidth={2.4} />
            </span>
          )}
        </div>
        <h1 className="m-0 text-[30px] font-bold leading-[1.2] tracking-[-0.02em]">{headline}</h1>
        <p className="m-0 max-w-[520px] text-base text-ink-muted" role={analysis.status === 'failed' ? 'alert' : undefined}>
          {subline}
        </p>
      </div>

      <div className="flex flex-col gap-[22px] rounded-[14px] border border-line bg-surface p-7">
        <div className="flex flex-col gap-2">
          <div className="flex justify-between text-sm">
            <span className="font-semibold">Progression</span>
            <span className="tabular-nums text-ink-muted">{pct} %</span>
          </div>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            aria-label="Progression de l'analyse"
            className="h-2 overflow-hidden rounded-full bg-surface-3"
          >
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        <ol className="m-0 flex list-none flex-col gap-1 p-0">
          {analysis.steps.map((st) => {
            const isDone = st.state === 'done';
            const isActive = st.state === 'active' && running;
            return (
              <li key={st.key} className="flex items-center gap-3.5 py-2.5">
                <span
                  className={`box-border flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border-2 ${
                    isDone ? 'border-accent bg-primary' : isActive ? 'border-accent bg-surface' : 'border-line-strong bg-surface'
                  }`}
                >
                  {isDone && <Icons.check size={14} strokeWidth={3} className="text-white" />}
                  {isActive && (
                    <svg className="ad-spin" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke="var(--nn-primary)" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                  )}
                </span>
                <span className="flex flex-grow flex-col">
                  <span className={`font-semibold ${isDone || isActive ? 'text-ink' : 'text-ink-muted'}`}>{st.label}</span>
                  <span className="text-[13px] text-ink-muted">{st.detail}</span>
                </span>
                <span className="text-[13px] tabular-nums text-ink-muted">
                  {isDone ? 'Terminé' : isActive ? `${st.progress} %` : 'En attente'}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="flex flex-col gap-3.5 rounded-[14px] border border-line bg-surface px-7 py-6">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-body">
            {flow ? 'Étapes qui émergent' : 'Thèmes qui émergent'}
          </span>
          <span className="text-[13px] text-ink-muted">· aperçu en direct</span>
        </div>
        <div className="flex min-h-[38px] flex-wrap gap-2">
          {analysis.preview.map((label, i) => {
            const c = themeColor(i);
            return (
              <span
                key={label + i}
                className="ad-fade inline-flex items-center gap-2 rounded-full px-3.5 py-[7px] text-sm font-semibold"
                style={{ background: c.soft, color: c.ink }}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: c.ink }} />
                {label}
              </span>
            );
          })}
          {running && <span className="ad-shimmer inline-block h-9 w-[140px] rounded-full" />}
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-3">
        {running && (
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex min-h-11 items-center rounded-[10px] border border-line-strong bg-surface px-5 font-semibold text-ink hover:bg-bg"
          >
            Annuler l'analyse
          </button>
        )}
        {done && (
          <button
            type="button"
            onClick={onShowResult}
            className="inline-flex min-h-12 items-center gap-2.5 rounded-[10px] border-none bg-primary px-6 font-bold text-white hover:bg-primary-hover"
          >
            Voir la synthèse
            <Icons.arrow size={18} strokeWidth={2.2} />
          </button>
        )}
        {!running && !done && (
          <button
            type="button"
            onClick={onBack}
            className="inline-flex min-h-11 items-center rounded-[10px] border-none bg-primary px-5 font-semibold text-white hover:bg-primary-hover hover:opacity-90"
          >
            Retour à la configuration
          </button>
        )}
      </div>
    </main>
  );
};
