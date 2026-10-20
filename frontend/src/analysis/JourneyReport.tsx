import React from 'react';
import { Analysis, JourneyResult, Priority } from './types';
import { FlowDiagram } from './FlowDiagram';
import { Disclaimer, Emphasis, ReportBanner, docCountLabel, modelLabel } from './ui';

const SEVERITY: Record<Priority['severity'], [string, string]> = {
  Bloquant: ['#FCE4E2', '#9B2216'],
  Majeur: ['#FCEFE6', '#8A3E0A'],
  Mineur: ['#F1F2F6', '#3E4452'],
};

/** Ressenti -2…2 → ordonnée dans un repère de 110 px (positif en haut). */
const moodY = (sentiment: number) => 55 - sentiment * 18.5;

const RowLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="border-t border-hair py-[18px] text-[13px] font-semibold text-body">{children}</div>
);

export const JourneyReport: React.FC<{ analysis: Analysis; result: JourneyResult; onNewAnalysis: () => void }> = ({
  analysis,
  result,
  onNewAnalysis,
}) => {
  const n = result.phases.length;
  const phases = result.phases.map((p, i) => ({
    ...p,
    n: i + 1,
    left: `${((i + 0.5) / n) * 100}%`,
    y: moodY(p.sentiment),
    moodColor: p.sentiment < 0 ? '#B04C0D' : 'var(--ad-ink)',
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
        chips={[analysis.mode_label, analysis.level_label, docCountLabel(analysis.documents.length), modelLabel(analysis)]}
      />

      <main className="mx-auto box-border flex max-w-[1280px] flex-col gap-7 px-8 pb-24 pt-8">
        <section aria-labelledby="bref-h" className="flex flex-wrap items-stretch gap-7">
          <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-3.5 rounded-2xl bg-ink px-[34px] py-[30px] text-white">
            <h2 id="bref-h" className="m-0 text-[13px] font-semibold uppercase tracking-[0.1em] text-[#C9CDF5]">
              En bref
            </h2>
            <p className="m-0 font-serif text-[22px] leading-[1.45]">
              <Emphasis text={result.brief} />
            </p>
          </div>
          <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-3.5 rounded-2xl border border-line bg-white px-[26px] py-6">
            <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-body">Légende</span>
            <div className="flex items-center gap-2.5 text-sm">
              <span className="h-3 w-3 rounded-[3px] bg-[#C2560F]" />
              Friction ou point de rupture
            </div>
            <div className="flex items-center gap-2.5 text-sm">
              <span className="h-3 w-3 rounded-[3px] bg-[#2F5BD8]" />
              Opportunité d'amélioration
            </div>
            <div className="flex items-center gap-2.5 text-sm">
              <span className="box-border h-3 w-3 rounded-full border-[3px] border-ink" />
              Ressenti moyen exprimé
            </div>
          </div>
        </section>

        {/* Carte de parcours */}
        <section aria-labelledby="map-h" className="rounded-2xl border border-line bg-white pb-2 pt-7">
          <h2 id="map-h" className="mx-[34px] mb-5 mt-0 text-[22px] font-bold tracking-[-0.01em]">
            Carte du parcours
          </h2>
          <div className="overflow-x-auto">
            <div className="grid gap-x-3 px-[34px] pb-6" style={grid}>
              <div />
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-col gap-1 rounded-xl bg-page px-4 py-3.5">
                  <span className="text-xs font-semibold text-muted">Étape {ph.n}</span>
                  <span className="text-base font-bold">{ph.name}</span>
                </div>
              ))}

              <div className="pt-5 text-[13px] font-semibold text-body">Ressenti</div>
              <div className="relative mt-3 h-[150px]" style={{ gridColumn: `span ${n}` }}>
                <svg
                  width="100%"
                  height="110"
                  viewBox="0 0 1000 110"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                  className="absolute left-0 top-0"
                >
                  <line x1="0" y1="55" x2="1000" y2="55" stroke="var(--ad-line)" strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
                  <polyline points={curve} fill="none" stroke="var(--ad-ink)" strokeWidth="2.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                </svg>
                {phases.map((ph) => (
                  <React.Fragment key={ph.n}>
                    <span
                      className="absolute box-border h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3.5px] bg-white"
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
                <span className="absolute left-0 top-0 text-[11px] text-muted">positif</span>
                <span className="absolute left-0 top-[94px] text-[11px] text-muted">négatif</span>
              </div>

              <RowLabel>Ce que fait l'utilisateur</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="border-t border-hair px-1 py-[18px] text-sm leading-normal text-[#22252D]">
                  {ph.does}
                </div>
              ))}

              <RowLabel>Points de contact</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-wrap content-start gap-1.5 border-t border-hair px-1 py-[18px]">
                  {ph.touchpoints.map((tc) => (
                    <span key={tc} className="rounded-md border border-line-strong px-[9px] py-[3px] text-xs text-chip-ink">
                      {tc}
                    </span>
                  ))}
                </div>
              ))}

              <RowLabel>Frictions</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-col gap-2 border-t border-hair py-[18px]">
                  {ph.frictions.map((fr) => (
                    <span key={fr} className="rounded-lg bg-[#FCEFE6] px-[11px] py-[9px] text-[13px] leading-[1.4] text-[#7E3A0A]">
                      {fr}
                    </span>
                  ))}
                </div>
              ))}

              <RowLabel>Opportunités</RowLabel>
              {phases.map((ph) => (
                <div key={ph.n} className="flex flex-col gap-2 border-t border-hair py-[18px]">
                  {ph.opportunities.map((op) => (
                    <span key={op} className="rounded-lg bg-[#EAF0FD] px-[11px] py-[9px] text-[13px] leading-[1.4] text-[#1F3F9E]">
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
          <section aria-labelledby="flow-h" className="flex flex-col gap-5 rounded-2xl border border-line bg-white px-[34px] py-7">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
              <h2 id="flow-h" className="m-0 text-[22px] font-bold tracking-[-0.01em]">
                Flux et points de sortie
              </h2>
              <span className="text-sm text-muted">Reconstitué à partir des récits des participants</span>
            </div>
            <FlowDiagram graph={result.flow} />
          </section>
        )}

        {/* Frictions prioritaires */}
        {result.priorities.length > 0 && (
          <section aria-labelledby="pri-h" className="flex flex-col gap-1.5 rounded-2xl border border-line bg-white px-[34px] py-7">
            <h2 id="pri-h" className="m-0 mb-3 text-[22px] font-bold tracking-[-0.01em]">
              Frictions prioritaires
            </h2>
            {result.priorities.map((pr, i) => {
              const [bg, fg] = SEVERITY[pr.severity];
              return (
                <div key={i} className="flex flex-wrap items-start gap-x-5 gap-y-3 border-t border-hair py-[18px]">
                  <span
                    className="w-[76px] shrink-0 rounded-md px-2.5 py-1 text-center text-xs font-bold"
                    style={{ background: bg, color: fg }}
                  >
                    {pr.severity}
                  </span>
                  <div className="flex min-w-0 flex-[999_1_420px] flex-col gap-1.5">
                    <span className="text-base font-bold">{pr.title}</span>
                    <span className="font-serif text-[17px] leading-[1.55] text-prose">{pr.body}</span>
                    {pr.quote && <span className="font-serif text-base italic text-body">« {pr.quote} »</span>}
                  </div>
                  <div className="flex flex-[1_1_180px] flex-col gap-1.5 text-[13px] text-muted">
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

        <Disclaimer />
      </main>
    </>
  );
};
