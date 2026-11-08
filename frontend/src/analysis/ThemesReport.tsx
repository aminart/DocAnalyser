import React, { useState } from 'react';
import { SourcePanel } from './SourcePanel';
import { Analysis, SourceRequest, ThemesResult } from './types';
import {
  Disclaimer,
  Emphasis,
  FileBadge,
  Icons,
  ReportBanner,
  ReportTabs,
  docCountLabel,
  extOf,
  modelLabel,
  CoverageNote,
  QuoteNotice,
  shortDocName,
  themeColor,
} from './ui';

const ACTIONS_LABEL: Record<string, string> = {
  global: "Pistes d'action",
  transcript: 'Décisions et prochaines étapes',
  notes: 'Prochaines étapes',
};

const scrollTo = (id: string) => (e: React.MouseEvent) => {
  e.preventDefault();
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

export const ThemesReport: React.FC<{ analysis: Analysis; result: ThemesResult; onNewAnalysis: () => void; tabs?: ReportTabs }> = ({
  analysis,
  result,
  onNewAnalysis,
  tabs,
}) => {
  const [closed, setClosed] = useState<number[]>([]);
  const [source, setSource] = useState<SourceRequest | null>(null);
  const nDocs = analysis.documents.length;
  // Tout ce que le modèle a rédigé est affiché : le niveau a déjà réglé la profondeur de la synthèse.
  const showSources = analysis.cite;
  const actionsLabel = ACTIONS_LABEL[analysis.mode] ?? ACTIONS_LABEL.global;

  const themes = result.themes.map((t, i) => ({
    ...t,
    ...themeColor(i),
    num: i + 1,
    anchor: `theme-${i + 1}`,
    presence: `Présent dans ${t.documents.length}/${nDocs} document${nDocs > 1 ? 's' : ''}`,
    open: !closed.includes(i),
  }));

  const stats = [
    [result.stats.themes, 'grands thèmes'],
    [result.stats.points, 'points clés'],
    [result.stats.quotes, result.stats.quotes_exact === result.stats.quotes ? 'verbatims, tous vérifiés' : `verbatims (${result.stats.quotes_exact} vérifiés mot pour mot)`],
    [result.stats.actions, actionsLabel.toLowerCase()],
  ] as const;

  return (
    <>
      <ReportBanner
        analysis={analysis}
        onNewAnalysis={onNewAnalysis}
        tabs={tabs}
        showCopy
        chips={[analysis.mode_label, analysis.level_label, docCountLabel(nDocs), modelLabel(analysis)]}
      />

      <div className="mx-auto box-border flex max-w-[1280px] flex-wrap items-start gap-10 px-8 pb-24 pt-8">
        {/* Sommaire */}
        <aside
          aria-label="Sommaire"
          className="flex min-w-0 max-w-[300px] flex-[1_1_240px] flex-col gap-6 lg:sticky lg:top-6"
        >
          <nav className="flex flex-col gap-1">
            <span className="px-3 pb-2 text-xs font-semibold uppercase tracking-[0.08em] text-ink-body">Sommaire</span>
            <a href="#bref" onClick={scrollTo('bref')} className="flex items-center gap-2.5 rounded-lg px-3 py-[9px] font-semibold text-ink no-underline hover:bg-surface">
              En bref
            </a>
            {themes.map((t) => (
              <a
                key={t.anchor}
                href={`#${t.anchor}`}
                onClick={scrollTo(t.anchor)}
                className="flex items-center gap-2.5 rounded-lg px-3 py-[9px] text-ink no-underline hover:bg-surface"
              >
                <span
                  className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md text-xs font-bold"
                  style={{ background: t.soft, color: t.ink }}
                >
                  {t.num}
                </span>
                <span className="flex-grow font-medium leading-[1.3]">{t.title}</span>
                <span className="text-xs text-ink-muted">{t.points.length}</span>
              </a>
            ))}
            {result.actions.length > 0 && (
              <a href="#actions" onClick={scrollTo('actions')} className="flex items-center gap-2.5 rounded-lg px-3 py-[9px] font-semibold text-ink no-underline hover:bg-surface">
                {actionsLabel}
              </a>
            )}
          </nav>
          <div className="flex flex-col gap-2.5 border-t border-line pt-5">
            <span className="px-3 text-xs font-semibold uppercase tracking-[0.08em] text-ink-body">Sources</span>
            {result.sources.map((s) => {
              const doc = analysis.documents.find((d) => d.name === s.document);
              const unused = analysis.cite && s.citations === 0 && !result.themes.some((t) => t.documents.includes(s.document));
              return (
                <div key={s.document} className="flex flex-col gap-1 px-3 text-[13px]">
                  <div className="flex items-center gap-2.5" title={s.document}>
                    <FileBadge ext={extOf(s.document)} size="sm" />
                    <span className="min-w-0 flex-grow truncate">{s.document}</span>
                    {analysis.cite && <span className="text-ink-muted">{s.citations} cit.</span>}
                  </div>
                  {unused && <span className="pl-8 text-xs text-warning-text">Aucun élément retenu de ce document</span>}
                  {doc?.warnings.map((w) => (
                    <span key={w} className="pl-8 text-xs text-warning-text">
                      {w}
                    </span>
                  ))}
                </div>
              );
            })}
            <div className="px-3 pt-1">
              <CoverageNote coverage={result.coverage} />
            </div>
          </div>
        </aside>

        {/* Contenu */}
        <main className="flex min-w-0 max-w-[820px] flex-[999_1_620px] flex-col gap-7">
          <section
            id="bref"
            aria-labelledby="bref-h"
            className="flex scroll-mt-6 flex-col gap-[22px] rounded-2xl bg-[#15171C] px-9 py-8 text-white dark:border dark:border-line dark:bg-surface-2"
          >
            <h2 id="bref-h" className="m-0 text-[13px] font-semibold uppercase tracking-[0.1em] text-[#C9CDF5]">
              En bref
            </h2>
            <p className="m-0 text-2xl font-normal leading-[1.45]">
              <Emphasis text={result.brief} />
            </p>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
              {stats.map(([value, label]) => (
                <div key={label} className="rounded-xl border border-[#343845] dark:border-line-strong px-4 py-3.5">
                  <div className="text-[26px] font-bold">{value}</div>
                  <div className="text-[13px] text-[#C2C6D0]">{label}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Carte des thèmes */}
          <section aria-label="Vue d'ensemble des thèmes" className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
            {themes.map((t) => (
              <a
                key={t.anchor}
                href={`#${t.anchor}`}
                onClick={scrollTo(t.anchor)}
                className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface p-[18px] text-ink no-underline transition hover:border-line-strong"
              >
                <span className="flex items-center justify-between">
                  <span
                    className="flex h-7 w-7 items-center justify-center rounded-lg font-bold"
                    style={{ background: t.soft, color: t.ink }}
                  >
                    {t.num}
                  </span>
                  <span className="text-xs text-ink-muted">{t.presence}</span>
                </span>
                <span className="text-[15px] font-bold leading-[1.3]">{t.title}</span>
                <span className="flex gap-[3px]" aria-label={`Présent dans ${t.documents.length} documents sur ${nDocs}`}>
                  {analysis.documents.map((d, k) => (
                    <span
                      key={d.id}
                      className="h-[5px] flex-grow rounded-[3px]"
                      style={{ background: k < t.documents.length ? t.ink : 'var(--nn-line)' }}
                    />
                  ))}
                </span>
              </a>
            ))}
          </section>

          {/* Thèmes */}
          {themes.map((t, i) => (
            <section
              key={t.anchor}
              id={t.anchor}
              aria-labelledby={`${t.anchor}-h`}
              className="scroll-mt-6 overflow-hidden rounded-2xl border border-line bg-surface"
            >
              <div className="h-1" style={{ background: t.ink }} />
              <div className="flex items-start gap-4 px-9 pb-2 pt-7">
                <span
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] text-lg font-bold"
                  style={{ background: t.soft, color: t.ink }}
                >
                  {t.num}
                </span>
                <div className="flex min-w-0 flex-grow flex-col gap-1">
                  <h2 id={`${t.anchor}-h`} className="m-0 text-2xl font-bold leading-[1.25] tracking-[-0.01em]">
                    {t.title}
                  </h2>
                  <span className="text-[13px] text-ink-muted">
                    {t.presence} · {t.points.length} point{t.points.length > 1 ? 's' : ''} clé{t.points.length > 1 ? 's' : ''}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setClosed(t.open ? [...closed, i] : closed.filter((x) => x !== i))}
                  aria-expanded={t.open}
                  aria-label={t.open ? 'Réduire le thème' : 'Déplier le thème'}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] border border-line bg-surface text-ink-muted hover:bg-bg"
                >
                  <Icons.chevron
                    size={18}
                    style={{ transform: `rotate(${t.open ? 180 : 0}deg)`, transition: 'transform 0.2s' }}
                  />
                </button>
              </div>

              {t.open && (
                <div className="flex flex-col gap-6 px-9 pb-8 pt-2 sm:pl-[92px]">
                  <p className="m-0 text-[19px] leading-[1.6] text-ink">{t.summary}</p>

                  <ul className="m-0 flex list-none flex-col gap-4 p-0">
                    {t.points.map((p, k) => (
                      <li key={k} className="flex gap-3.5">
                        <span className="mt-[9px] h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: t.ink }} />
                        <div className="flex flex-col gap-1.5">
                          <span className="text-base font-bold leading-[1.4]">{p.lead}</span>
                          {p.body && (
                            <span className=" text-[17px] leading-[1.6] text-ink-body">{p.body}</span>
                          )}
                          {showSources && p.sources.length > 0 && (
                            <span className="flex flex-wrap gap-1.5">
                              {p.sources.map((s, j) => (
                                <button
                                  key={j}
                                  type="button"
                                  onClick={() =>
                                    setSource({ document: s.document, location: s.location, text: `${p.lead} ${p.body}`.trim() })
                                  }
                                  title={
                                    s.found === false
                                      ? `Repère « ${s.location} » introuvable dans ${s.document} : cliquer pour voir le passage le plus proche`
                                      : `Voir le passage d'origine : ${s.document} — ${s.location}`
                                  }
                                  className={`inline-flex items-center gap-[5px] rounded-md border px-2 py-0.5 text-xs transition hover:border-accent hover:text-accent-ink ${
                                    s.found === false
                                      ? 'border-dashed border-warning bg-surface text-warning-text'
                                      : 'border-line bg-bg text-ink-muted'
                                  }`}
                                >
                                  <Icons.file size={12} />
                                  {[shortDocName(s.document), s.location].filter(Boolean).join(' ')}
                                </button>
                              ))}
                            </span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>

                  {t.quote && (
                    <figure
                      className={`m-0 flex flex-col gap-2.5 rounded-xl px-[26px] py-[22px] ${
                        t.quote_check === 'absent' ? 'border border-dashed border-warning' : ''
                      }`}
                      style={{ background: t.quote_check === 'absent' ? 'var(--nn-surface)' : t.soft }}
                    >
                      <blockquote className="m-0 text-[21px] italic leading-normal text-ink">
                        « {t.quote} »
                      </blockquote>
                      {t.quote_by && (
                        <figcaption className="text-[13px] font-semibold" style={{ color: t.ink }}>
                          {t.quote_by}
                        </figcaption>
                      )}
                      <QuoteNotice check={t.quote_check} />
                      <button
                        type="button"
                        onClick={() => setSource({ document: '', location: '', text: t.quote })}
                        className="w-fit border-none bg-transparent p-0 text-[13px] font-semibold text-accent underline-offset-2 hover:underline"
                      >
                        Voir dans le document
                      </button>
                    </figure>
                  )}

                  {t.nuance && (
                    <div className="flex gap-3 rounded-xl border border-dashed border-line-dashed px-[18px] py-4">
                      <Icons.nuance size={20} className="mt-0.5 shrink-0 text-ink-muted" />
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[13px] font-bold text-ink-muted">Nuance / point de divergence</span>
                        <span className="text-[15px] leading-[1.55] text-ink-body">{t.nuance}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>
          ))}

          {/* Pistes d'action */}
          {result.actions.length > 0 && (
            <section
              id="actions"
              aria-labelledby="actions-h"
              className="flex scroll-mt-6 flex-col gap-[18px] rounded-2xl border border-line bg-surface px-9 py-7"
            >
              <h2 id="actions-h" className="m-0 text-2xl font-bold tracking-[-0.01em]">
                {actionsLabel}
              </h2>
              <ol className="m-0 flex list-none flex-col p-0">
                {result.actions.map((a, i) => {
                  const c = a.theme ? themeColor(a.theme - 1) : null;
                  return (
                    <li key={i} className="flex items-start gap-4 border-t border-surface-3 py-4">
                      <span className="w-7 shrink-0 text-[28px] leading-none text-ink-subtle">{i + 1}</span>
                      <div className="flex flex-grow flex-col gap-1.5">
                        <span className="text-base font-bold">{a.title}</span>
                        <span className="text-[15px] leading-[1.55] text-ink-body">{a.body}</span>
                      </div>
                      {c && (
                        <span
                          className="whitespace-nowrap rounded-full px-2.5 py-[3px] text-xs font-semibold"
                          style={{ background: c.soft, color: c.ink }}
                        >
                          Thème {a.theme}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          )}

          <Disclaimer />
        </main>
      </div>
      <SourcePanel analysisId={analysis.id} request={source} onClose={() => setSource(null)} />
    </>
  );
};
