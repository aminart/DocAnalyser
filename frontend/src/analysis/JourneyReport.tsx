import React, { useState } from 'react';
import { SourcePanel } from './SourcePanel';
import { Analysis, JourneyResult, Priority, SourceRequest } from './types';
import { FlowDiagram } from './FlowDiagram';
import { CoverageNote, Disclaimer, Emphasis, QuoteNotice, ReportBanner, ReportTabs, docCountLabel, modelLabel } from './ui';

const SEVERITY: Record<Priority['severity'], [string, string]> = {
  Bloquant: ['var(--nn-danger-soft)', 'var(--nn-danger-text)'],
  Majeur: ['var(--nn-warning-soft)', 'var(--nn-warning-text)'],
  Mineur: ['var(--nn-surface-3)', 'var(--nn-ink-muted)'],
};

/** Ressenti -2…2 → ordonnée dans un repère de 110 px (positif en haut). */
const moodY = (sentiment: number) => 55 - sentiment * 18.5;

const RowLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="border-t border-surface-3 py-[18px] text-[13px] font-semibold text-ink-body">{children}</div>
);

export const JourneyReport: React.FC<{ analysis: Analysis; result: JourneyResult; onNewAnalysis: () => void; tabs?: ReportTabs }> = ({
  analysis,
  result,
  onNewAnalysis,
  tabs,
}) => {
  const [source, setSource] = useState<SourceRequest | null>(null);
  const n = result.phases.length;
  const phases = result.phases.map((p, i) => ({
    ...p,
    n: i + 1,
    left: `${((i + 0.5) / n) * 100}%`,
    y: moodY(p.sentiment),
    moodColor: p.sentiment < 0 ? 'var(--nn-warning)' : 'var(--nn-ink)',
  }));
  const curve = phases.map((p, i) => `${((i + 0.5) / n) * 1000},${p.y}`).join(' ');
  const grid: React.CSSProperties = {
    gridTemplateColumns: `150px repeat(${n}, minmax(0, 1fr))`,
    minWidth: 150 + n * 186,
  };

  return (
    <>
      <ReportBanner
        analysis={analysis}
        onNewAnalysis={onNewAnalysis}
        tabs={tabs}
        chips={[analysis.mode_label, analysis.level_label, docCountLabel(analysis.documents.length), modelLabel(analysis)]}
      />

      <main className="mx-auto box-border flex max-w-[1280px] flex-col gap-7 px-8 pb-24 pt-8">
        <section aria-labelledby="bref-h" className="flex flex-wrap items-stretch gap-7">
          <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-3.5 rounded-2xl bg-[#15171C] px-[34px] py-[30px] text-white dark:border dark:border-line dark:bg-surface-2">
            <h2 id="bref-h" className="m-0 text-[13px] font-semibold uppercase tracking-[0.1em] text-[#C9CDF5]">
              En bref
            </h2>
            <p className="m-0 text-[22px] leading-[1.45]">
              <Emphasis text={result.brief} />
            </p>
          </div>
          <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-3.5 rounded-2xl border border-line bg-surface px-[26px] py-6">
            <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-body">Légende</span>
            <div className="flex items-center gap-2.5 text-sm">
              <span className="h-3 w-3 rounded-[3px] bg-warning" />
              Friction ou point de rupture
            </div>
            <div className="flex items-center gap-2.5 text-sm">
              <span className="h-3 w-3 rounded-[3px] bg-primary" />
              Opportunité d'amélioration
            </div>
            <div className="flex items-center gap-2.5 text-sm">
              <span className="box-border h-3 w-3 rounded-full border-[3px] border-ink" />
              Ressenti moyen exprimé
            </div>
            <p className="m-0 mt-auto text-xs leading-normal text-ink-muted">
              Ressenti et gravité sont estimés par le modèle à partir de ce qu'expriment les documents.
            </p>
            <CoverageNote coverage={result.coverage} />
          </div>
        </section>

        {/* Carte de parcours */}
        <section aria-labelledby="map-h" className="rounded-2xl border border-line bg-surface pb-2 pt-7">
          <h2 id="map-h" className="mx-[34px] mb-5 mt-0 text-[22px] font-bold tracking-[-0.01em]">
            Carte du parcours
          </h2>
          <div className="overflow-x-auto">
            <div className="grid gap-x-3 px-[34px] pb-6" style={grid}>
              <div />
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-col gap-1 rounded-xl bg-bg px-4 py-3.5">
                  <span className="text-xs font-semibold text-ink-muted">Étape {ph.n}</span>
                  <span className="text-base font-bold">{ph.name}</span>
                </div>
              ))}

              <div className="pt-5 text-[13px] font-semibold text-ink-body">Ressenti</div>
              <div className="relative mt-3 h-[150px]" style={{ gridColumn: `span ${n}` }}>
                <svg
                  width="100%"
                  height="110"
                  viewBox="0 0 1000 110"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                  className="absolute left-0 top-0"
                >
                  <line x1="0" y1="55" x2="1000" y2="55" stroke="var(--nn-line)" strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
                  <polyline points={curve} fill="none" stroke="var(--nn-ink)" strokeWidth="2.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                </svg>
                {phases.map((ph) => (
                  <React.Fragment key={ph.n}>
                    <span
                      className="absolute box-border h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3.5px] bg-surface"
                      style={{ left: ph.left, top: ph.y, borderColor: ph.moodColor }}
                    />
                    <span
                      className="absolute top-[118px] -translate-x-1/2 whitespace-nowrap text-[13px] font-semibold"
                      style={{ left: ph.left, color: ph.moodColor }}
                    >
                      {ph.mood}
                    </span>
                  </React.Fragment>
                ))}
                <span className="absolute left-0 top-0 text-[11px] text-ink-muted">positif</span>
                <span className="absolute left-0 top-[94px] text-[11px] text-ink-muted">négatif</span>
              </div>

              <RowLabel>Ce que fait l'utilisateur</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="border-t border-surface-3 px-1 py-[18px] text-sm leading-normal text-ink">
                  {ph.does}
                </div>
              ))}

              <RowLabel>Points de contact</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-wrap content-start gap-1.5 border-t border-surface-3 px-1 py-[18px]">
                  {ph.touchpoints.map((tc) => (
                    <span key={tc} className="rounded-md border border-line-strong px-[9px] py-[3px] text-xs text-ink-muted">
                      {tc}
                    </span>
                  ))}
                </div>
              ))}

              <RowLabel>Frictions</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-col gap-2 border-t border-surface-3 py-[18px]">
                  {ph.frictions.map((fr) => (
                    <span key={fr} className="rounded-lg bg-warning-soft px-[11px] py-[9px] text-[13px] leading-[1.4] text-warning-text">
                      {fr}
                    </span>
                  ))}
                </div>
              ))}

              <RowLabel>Opportunités</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-col gap-2 border-t border-surface-3 py-[18px]">
                  {ph.opportunities.map((op) => (
                    <span key={op} className="rounded-lg bg-accent-softer px-[11px] py-[9px] text-[13px] leading-[1.4] text-accent-ink">
                      {op}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Flux et points de sortie : graphe libre (linéaire, ramifié, avec boucles…) */}
        {result.flow.nodes.length > 0 && (
          <section aria-labelledby="flow-h" className="flex flex-col gap-5 rounded-2xl border border-line bg-surface px-[34px] py-7">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
              <h2 id="flow-h" className="m-0 text-[22px] font-bold tracking-[-0.01em]">
                Flux et points de sortie
              </h2>
              <span className="text-sm text-ink-muted">Reconstitué à partir des récits des participants</span>
            </div>
            <FlowDiagram graph={result.flow} />
          </section>
        )}

        {/* Frictions prioritaires */}
        {result.priorities.length > 0 && (
          <section aria-labelledby="pri-h" className="flex flex-col gap-1.5 rounded-2xl border border-line bg-surface px-[34px] py-7">
            <h2 id="pri-h" className="m-0 mb-3 text-[22px] font-bold tracking-[-0.01em]">
              Frictions prioritaires
            </h2>
            {result.priorities.map((pr, i) => {
              const [bg, fg] = SEVERITY[pr.severity];
              return (
                <div key={i} className="flex flex-wrap items-start gap-x-5 gap-y-3 border-t border-surface-3 py-[18px]">
                  <span
                    className="w-[76px] shrink-0 rounded-md px-2.5 py-1 text-center text-xs font-bold"
                    style={{ background: bg, color: fg }}
                  >
                    {pr.severity}
                  </span>
                  <div className="flex min-w-0 flex-[999_1_420px] flex-col gap-1.5">
                    <span className="text-base font-bold">{pr.title}</span>
                    <span className=" text-[17px] leading-[1.55] text-ink-body">{pr.body}</span>
                    {pr.quote && <span className=" text-base italic text-ink-body">« {pr.quote} »</span>}
                    {pr.quote && <QuoteNotice check={pr.quote_check} />}
                    {pr.quote && (
                      <button
                        type="button"
                        onClick={() => setSource({ document: '', location: '', text: pr.quote })}
                        className="w-fit border-none bg-transparent p-0 text-[13px] font-semibold text-accent underline-offset-2 hover:underline"
                      >
                        Voir dans le document
                      </button>
                    )}
                  </div>
                  <div className="flex flex-[1_1_180px] flex-col gap-1.5 text-[13px] text-ink-muted">
                    {pr.phase && (
                      <span>
                        Étape : <strong className="text-ink">{pr.phase}</strong>
                      </span>
                    )}
                    {pr.frequency && (
                      <span>
                        Cité par <strong className="text-ink">{pr.frequency}</strong>
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </section>
        )}

        {result.extra.length > 0 && (
          <section aria-labelledby="extra-h" className="flex flex-col gap-3 rounded-2xl border border-line bg-surface px-[34px] py-7">
            <h2 id="extra-h" className="m-0 text-[22px] font-bold tracking-[-0.01em]">
              Autres éléments des documents
            </h2>
            <p className="m-0 text-sm text-ink-muted">
              Informations présentes dans les documents mais non intégrées au parcours ci-dessus, reprises telles
              qu'extraites.
            </p>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {result.extra.map((e, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-surface-3 pt-2 text-[15px] text-ink-body">
                  <span className="flex-[999_1_420px]">{e.text}</span>
                  {e.document && (
                    <button
                      type="button"
                      onClick={() => setSource({ document: e.document, location: e.location, text: e.text })}
                      className="border-none bg-transparent p-0 text-xs text-accent underline-offset-2 hover:underline"
                    >
                      {e.document} {e.location}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        <Disclaimer />
      </main>
      <SourcePanel analysisId={analysis.id} request={source} onClose={() => setSource(null)} />
    </>
  );
};
