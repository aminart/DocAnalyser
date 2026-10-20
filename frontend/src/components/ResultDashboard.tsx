import React, { useState } from 'react';
import { synthesisApi } from '../services/api';
import {
  DocumentPreviewBlock,
  ExportFormat,
  GlobalSummaryResult,
  JobStatusResponse,
  RawNotesResult,
  SourceReference,
  TranscriptSummaryResult,
  UserJourneyResult,
} from '../types/synthesis';
import { MermaidViewer } from './MermaidViewer';

interface ResultDashboardProps {
  job: JobStatusResponse;
  onExport: (format: ExportFormat) => void;
  onReset: () => void;
}

/**
 * Affiche le texte avec mise en valeur élégante des accroches en gras (**texte**)
 * pour une lecture fluide, aérée et immédiate.
 */
export const FormattedText: React.FC<{ text?: string | null; className?: string }> = ({
  text,
  className = '',
}) => {
  if (!text) return null;
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <span className={className}>
      {parts.map((part, idx) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={idx} className="font-bold text-slate-900">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={idx}>{part}</span>;
      })}
    </span>
  );
};

const SourceBadges: React.FC<{
  sources: SourceReference[];
  onSelectSource: (source: SourceReference) => void;
}> = ({ sources, onSelectSource }) => {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100/80 pt-2.5">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        Sources vérifiées :
      </span>
      {sources.map((src, idx) => (
        <button
          key={`${src.file_name}-${src.location}-${idx}`}
          type="button"
          onClick={() => onSelectSource(src)}
          className="citation-chip group cursor-pointer"
          title={`Extrait verbatim : "${src.excerpt}"`}
        >
          <span className="material-symbols-outlined text-[13px] text-indigo-500 transition group-hover:text-indigo-700">
            find_in_page
          </span>
          <span className="max-w-[140px] truncate">{src.file_name}</span>
          <span className="text-indigo-300">•</span>
          <span className="font-semibold text-indigo-900">{src.location}</span>
        </button>
      ))}
    </div>
  );
};

export const ResultDashboard: React.FC<ResultDashboardProps> = ({
  job,
  onExport,
  onReset,
}) => {
  const [activeSource, setActiveSource] = useState<SourceReference | null>(null);
  const [fullBlockContent, setFullBlockContent] = useState<string | null>(null);
  const [loadingBlock, setLoadingBlock] = useState(false);

  const handleSelectSource = async (src: SourceReference) => {
    setActiveSource(src);
    setFullBlockContent(null);

    const matchingDoc = job.documents.find((d) => d.file_name === src.file_name);
    if (!matchingDoc) return;

    try {
      setLoadingBlock(true);
      const preview = await synthesisApi.fetchDocumentBlocks(matchingDoc.document_id);
      const matchedBlock = preview.blocks.find(
        (b: DocumentPreviewBlock) => b.location === src.location
      );
      if (matchedBlock) {
        setFullBlockContent(matchedBlock.content);
      }
    } catch {
      // L'extrait source reste consultable
    } finally {
      setLoadingBlock(false);
    }
  };

  const handleDownloadJson = () => {
    const jsonStr = JSON.stringify(job.result, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `synthese_${job.mode}_${job.job_id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (job.stage !== 'ready' && job.stage !== 'failed') {
    return (
      <div className="mx-auto max-w-2xl rounded-2xl border border-slate-200 bg-white p-10 shadow-sm">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
            <span className="material-symbols-outlined animate-spin text-2xl">
              progress_activity
            </span>
          </div>
          <div>
            <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-indigo-700">
              {job.stage === 'parsing'
                ? 'Étape 1/2 : Parsing & Traçabilité'
                : 'Étape 2/2 : Analyse LLM & Synthèse'}
            </span>
            <h2 className="mt-1 text-xl font-bold text-slate-900">
              Traitement de {job.documents.length} document(s) avec {job.model_name}
            </h2>
          </div>
        </div>

        <div className="mt-8">
          <div className="mb-2 flex justify-between text-sm font-medium text-slate-700">
            <span>{job.current_step_detail}</span>
            <span className="font-bold text-indigo-600">{job.progress_percent}%</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-indigo-600 transition-all duration-500"
              style={{ width: `${job.progress_percent}%` }}
            />
          </div>
        </div>

        <div className="mt-6 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          {job.documents.map((doc) => (
            <span
              key={doc.document_id}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
            >
              <span className="material-symbols-outlined text-sm text-slate-500">description</span>
              {doc.file_name}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (job.stage === 'failed' || !job.result) {
    return (
      <div className="mx-auto max-w-2xl rounded-2xl border border-rose-200 bg-rose-50 p-8 text-rose-900">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-3xl text-rose-600">error</span>
          <h2 className="text-lg font-bold">Le traitement a rencontré une erreur</h2>
        </div>
        <p className="mt-3 text-sm text-rose-800">{job.error_message || 'Erreur inconnue.'}</p>
        <button
          onClick={onReset}
          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-700"
        >
          <span className="material-symbols-outlined text-base">restart_alt</span>
          Nouvelle analyse
        </button>
      </div>
    );
  }

  const { result } = job;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
      {/* Colonne Principale : Synthèse Structurée */}
      <div className="space-y-6 lg:col-span-8">
        {/* Barre d'en-tête & Exports */}
        <div className="flex flex-col justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                <span className="material-symbols-outlined text-[14px]">verified</span>
                Synthèse Vérifiée & Sourcée
              </span>
              <span className="text-xs text-slate-400">• Modèle : {job.model_name}</span>
            </div>
            <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-slate-900">
              {result.title}
            </h1>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onExport('md')}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
              title="Exporter en Markdown structuré"
            >
              <span className="material-symbols-outlined text-base">markdown</span>
              Markdown
            </button>
            <button
              onClick={() => onExport('docx')}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
              title="Exporter au format Microsoft Word"
            >
              <span className="material-symbols-outlined text-base">article</span>
              Word
            </button>
            <button
              onClick={() => onExport('pdf')}
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-700"
              title="Générer un PDF de synthèse imprimable"
            >
              <span className="material-symbols-outlined text-base">picture_as_pdf</span>
              PDF
            </button>
            <button
              onClick={handleDownloadJson}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
              title="Télécharger le fichier JSON brut de la synthèse"
            >
              <span className="material-symbols-outlined text-base text-indigo-600">data_object</span>
              JSON
            </button>
          </div>
        </div>

        {/* Vues spécialisées par mode */}
        {result.mode === 'global_summary' && (
          <GlobalSummaryView data={result} onSelectSource={handleSelectSource} />
        )}

        {result.mode === 'transcript_summary' && (
          <TranscriptSummaryView data={result} onSelectSource={handleSelectSource} />
        )}

        {result.mode === 'user_journey' && (
          <UserJourneyView data={result} onSelectSource={handleSelectSource} />
        )}

        {result.mode === 'raw_notes' && (
          <RawNotesView data={result} onSelectSource={handleSelectSource} />
        )}
      </div>

      {/* Colonne Latérale : Inspecteur de Traçabilité */}
      <aside className="space-y-6 lg:col-span-4">
        <div className="sticky top-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-indigo-600">find_in_page</span>
              <h3 className="font-bold text-slate-900">Inspecteur de Traçabilité</h3>
            </div>
            <button
              type="button"
              onClick={onReset}
              className="text-xs font-semibold text-indigo-600 transition hover:underline"
            >
              + Nouveau document
            </button>
          </div>

          {activeSource ? (
            <div className="mt-4 space-y-4">
              <div className="rounded-xl border border-indigo-100 bg-indigo-50/70 p-3.5">
                <div className="text-[11px] font-bold uppercase tracking-wider text-indigo-600">
                  Document Source
                </div>
                <div className="mt-0.5 text-sm font-bold text-slate-900">
                  {activeSource.file_name}
                </div>
                <div className="mt-2 inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-semibold text-indigo-700 shadow-xs">
                  <span className="material-symbols-outlined text-sm">location_on</span>
                  Emplacement : {activeSource.location}
                </div>
              </div>

              <div>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Extrait verbatim mobilisé
                </div>
                <blockquote className="mt-1.5 rounded-xl border-l-4 border-indigo-500 bg-slate-50 p-3.5 text-xs italic leading-relaxed text-slate-700">
                  « {activeSource.excerpt} »
                </blockquote>
              </div>

              {loadingBlock && (
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="material-symbols-outlined animate-spin text-sm">sync</span>
                  Chargement du contexte de page...
                </div>
              )}

              {fullBlockContent && (
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Contexte complet de la page / section
                  </div>
                  <div className="mt-1.5 max-h-56 overflow-y-auto whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">
                    {fullBlockContent}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="py-12 text-center text-slate-400">
              <span className="material-symbols-outlined text-4xl text-slate-300">ads_click</span>
              <p className="mt-2 text-xs font-medium leading-relaxed">
                Cliquez sur n'importe quel badge de citation pour inspecter la page, la slide ou la
                ligne exacte d'origine.
              </p>
            </div>
          )}

          <div className="mt-6 border-t border-slate-100 pt-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Corpus analysé ({job.documents.length})
            </h4>
            <ul className="mt-2 space-y-1.5">
              {job.documents.map((d) => (
                <li
                  key={d.document_id}
                  className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700"
                >
                  <span className="truncate font-medium">{d.file_name}</span>
                  <span className="ml-2 shrink-0 text-[11px] text-slate-400">
                    {(d.total_size_bytes / 1024).toFixed(0)} Ko
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>
    </div>
  );
};

/* ==============================================================================
 * MODE 1 : SYNTHÈSE DOCUMENTAIRE GLOBALE
 * ============================================================================== */
const GlobalSummaryView: React.FC<{
  data: GlobalSummaryResult;
  onSelectSource: (s: SourceReference) => void;
}> = ({ data, onSelectSource }) => (
  <div className="space-y-6">
    {/* 1. Chapeau Exécutif */}
    <section className="rounded-2xl border border-slate-200 border-l-4 border-l-indigo-600 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
          <span className="material-symbols-outlined text-indigo-600">auto_stories</span>
          Synthèse Exécutive
        </h2>
        <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700">
          Vue Stratégique
        </span>
      </div>

      <p className="mt-4 text-[15px] font-normal leading-relaxed text-slate-800">
        <FormattedText text={data.executive_summary} />
      </p>

      {data.executive_paragraphs && data.executive_paragraphs.length > 0 && (
        <div className="mt-6 space-y-4 border-t border-slate-100 pt-5">
          {data.executive_paragraphs.map((para, idx) => (
            <article
              key={idx}
              className="rounded-xl border border-slate-100 bg-slate-50/70 p-4 transition hover:bg-slate-50"
            >
              <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900">
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-indigo-100 text-xs font-bold text-indigo-700">
                  {idx + 1}
                </span>
                {para.heading}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">
                <FormattedText text={para.body} />
              </p>
              <SourceBadges sources={para.sources} onSelectSource={onSelectSource} />
            </article>
          ))}
        </div>
      )}
    </section>

    {/* 2. Indicateurs Clés & KPIs */}
    {data.key_metrics && data.key_metrics.length > 0 && (
      <section>
        <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500">
          <span className="material-symbols-outlined text-sm text-indigo-600">monitoring</span>
          Indicateurs Clés & Métriques Chiffrées
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {data.key_metrics.map((metric, idx) => (
            <div
              key={idx}
              className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs transition hover:shadow-sm"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  {metric.label}
                </span>
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-lg ${
                    metric.trend === 'up'
                      ? 'bg-emerald-50 text-emerald-600'
                      : metric.trend === 'down'
                      ? 'bg-rose-50 text-rose-600'
                      : 'bg-indigo-50 text-indigo-600'
                  }`}
                >
                  <span className="material-symbols-outlined text-base">
                    {metric.trend === 'up'
                      ? 'trending_up'
                      : metric.trend === 'down'
                      ? 'trending_down'
                      : 'equalizer'}
                  </span>
                </span>
              </div>
              <div className="mt-2 text-2xl font-black tracking-tight text-slate-900">
                {metric.value}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-slate-600">
                <FormattedText text={metric.context} />
              </p>
              <SourceBadges sources={metric.sources} onSelectSource={onSelectSource} />
            </div>
          ))}
        </div>
      </section>
    )}

    {/* 3. Thématiques Clés & Développements */}
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
          <span className="material-symbols-outlined text-indigo-600">category</span>
          Thématiques & Développements Analytiques
        </h2>
        <span className="text-xs text-slate-400">{data.key_themes.length} thèmes analysés</span>
      </div>

      <div className="mt-5 space-y-5">
        {data.key_themes.map((item, idx) => (
          <div
            key={idx}
            className="rounded-xl border border-slate-200/90 bg-white p-5 shadow-xs transition hover:border-indigo-300"
          >
            <h3 className="flex items-center gap-2 text-base font-bold text-slate-900">
              <span className="h-2 w-2 rounded-full bg-indigo-600" />
              {item.theme}
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-700">
              <FormattedText text={item.summary} />
            </p>

            {item.arguments.length > 0 && (
              <ul className="mt-4 space-y-2.5 rounded-xl border border-slate-100 bg-slate-50/70 p-4">
                {item.arguments.map((arg, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-xs leading-relaxed text-slate-700">
                    <span className="material-symbols-outlined mt-0.5 text-base text-indigo-600 shrink-0">
                      check_circle
                    </span>
                    <div>
                      <FormattedText text={arg} />
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <SourceBadges sources={item.sources} onSelectSource={onSelectSource} />
          </div>
        ))}
      </div>
    </section>

    {/* 4. Recommandations & Conclusions */}
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
          <span className="material-symbols-outlined text-indigo-600">lightbulb</span>
          Recommandations & Orientations
        </h2>
        <span className="text-xs text-slate-400">{data.recommendations.length} recommandations</span>
      </div>

      <div className="mt-4 space-y-3">
        {data.recommendations.map((rec, idx) => (
          <div
            key={idx}
            className="rounded-xl border border-slate-200/90 bg-white p-4 transition hover:border-slate-300"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-slate-900">{rec.title}</h3>
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  rec.priority === 'Haute'
                    ? 'bg-rose-50 text-rose-700 border border-rose-200'
                    : rec.priority === 'Moyenne'
                    ? 'bg-amber-50 text-amber-800 border border-amber-200'
                    : 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                }`}
              >
                Priorité {rec.priority}
              </span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-slate-700">
              <FormattedText text={rec.description} />
            </p>
            <SourceBadges sources={rec.sources} onSelectSource={onSelectSource} />
          </div>
        ))}
      </div>
    </section>
  </div>
);

/* ==============================================================================
 * MODE 2 : SYNTHÈSE DE TRANSCRIPTION
 * ============================================================================== */
const TranscriptSummaryView: React.FC<{
  data: TranscriptSummaryResult;
  onSelectSource: (s: SourceReference) => void;
}> = ({ data, onSelectSource }) => (
  <div className="space-y-6">
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <span className="material-symbols-outlined text-indigo-600">record_voice_over</span>
        Contexte & Ordre du Jour de la Session
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-slate-700">
        <FormattedText text={data.context} />
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {data.participants.map((p, idx) => (
          <span
            key={idx}
            className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-800"
          >
            <span className="material-symbols-outlined text-sm text-indigo-600">person</span>
            <strong>{p.name}</strong> ({p.role})
          </span>
        ))}
      </div>

      {data.agenda.length > 0 && (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Points traités
          </div>
          <ul className="mt-2 flex flex-wrap gap-2">
            {data.agenda.map((item, idx) => (
              <li
                key={idx}
                className="rounded-lg bg-slate-50 px-2.5 py-1 text-xs text-slate-700 border border-slate-200/60"
              >
                {idx + 1}. {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>

    {/* Décisions Actées */}
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-6">
      <h2 className="flex items-center gap-2 text-base font-bold text-emerald-950">
        <span className="material-symbols-outlined text-emerald-600">gavel</span>
        Décisions Actées ({data.decisions_made.length})
      </h2>
      <div className="mt-4 space-y-3">
        {data.decisions_made.map((d, idx) => (
          <div key={idx} className="rounded-xl bg-white p-4 shadow-sm border border-emerald-100">
            <div className="font-bold text-slate-900">{d.decision}</div>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">
              <FormattedText text={d.rationale} />
            </p>
            <SourceBadges sources={d.sources} onSelectSource={onSelectSource} />
          </div>
        ))}
      </div>
    </section>

    {/* Plan d'action */}
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
        <span className="material-symbols-outlined text-indigo-600">task_alt</span>
        Plan d'Action (Qui fait quoi, pour quand)
      </h2>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs uppercase text-slate-400">
            <tr>
              <th className="pb-3 pr-4">Action</th>
              <th className="pb-3 pr-4">Responsable</th>
              <th className="pb-3 pr-4">Échéance</th>
              <th className="pb-3">Sources</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.action_items.map((item, idx) => (
              <tr key={idx} className="transition hover:bg-slate-50/70">
                <td className="py-3 pr-4 text-xs font-semibold text-slate-900">
                  <FormattedText text={item.task} />
                </td>
                <td className="py-3 pr-4">
                  <span className="rounded-md bg-indigo-50 px-2 py-1 text-xs font-semibold text-indigo-700">
                    {item.assignee}
                  </span>
                </td>
                <td className="py-3 pr-4 text-xs text-slate-600">{item.due_date}</td>
                <td className="py-3">
                  <SourceBadges sources={item.sources} onSelectSource={onSelectSource} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>

    {/* Synthèse par Piliers */}
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
        <span className="material-symbols-outlined text-indigo-600">workspaces</span>
        Débats Thématiques & Retours d'Expérience
      </h2>
      <div className="mt-4 space-y-4">
        {data.thematic_clusters.map((cluster, idx) => (
          <div key={idx} className="rounded-xl border border-slate-100 bg-slate-50/70 p-4">
            <h3 className="font-bold text-slate-900">{cluster.tag}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-700">
              <FormattedText text={cluster.consolidated_notes} />
            </p>
            {cluster.key_takeaways && cluster.key_takeaways.length > 0 && (
              <ul className="mt-3 space-y-1.5 border-t border-slate-200/50 pt-2.5">
                {cluster.key_takeaways.map((takeaway, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
                    <span className="text-indigo-600 font-bold">•</span>
                    <FormattedText text={takeaway} />
                  </li>
                ))}
              </ul>
            )}
            <SourceBadges sources={cluster.sources} onSelectSource={onSelectSource} />
          </div>
        ))}
      </div>
    </section>

    {/* Points de tension */}
    {data.open_questions_and_tensions && data.open_questions_and_tensions.length > 0 && (
      <section className="rounded-2xl border border-amber-200 bg-amber-50/50 p-6">
        <h2 className="flex items-center gap-2 text-base font-bold text-amber-950">
          <span className="material-symbols-outlined text-amber-600">warning</span>
          Points de Tension & Questions en Suspens
        </h2>
        <div className="mt-4 space-y-3">
          {data.open_questions_and_tensions.map((t, idx) => (
            <div key={idx} className="rounded-xl bg-white p-4 shadow-sm border border-amber-100">
              <div className="font-bold text-slate-900">{t.topic}</div>
              <p className="mt-1 text-xs leading-relaxed text-slate-600">
                <FormattedText text={t.description} />
              </p>
              <SourceBadges sources={t.sources} onSelectSource={onSelectSource} />
            </div>
          ))}
        </div>
      </section>
    )}
  </div>
);

/* ==============================================================================
 * MODE 3 : PARCOURS UTILISATEURS
 * ============================================================================== */
const UserJourneyView: React.FC<{
  data: UserJourneyResult;
  onSelectSource: (s: SourceReference) => void;
}> = ({ data, onSelectSource }) => (
  <div className="space-y-6">
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {data.personas.map((persona, idx) => (
        <div key={idx} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-indigo-600">badge</span>
            <h3 className="font-bold text-slate-900">{persona.name}</h3>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-slate-600">
            <FormattedText text={persona.profile} />
          </p>
          <SourceBadges sources={persona.sources} onSelectSource={onSelectSource} />
        </div>
      ))}
    </section>

    <MermaidViewer chart={data.mermaid_diagram} />

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-base font-bold text-slate-900">Étapes Chronologiques du Parcours</h2>
      <div className="mt-4 space-y-4">
        {data.steps.map((step) => (
          <div
            key={step.step_number}
            className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition hover:bg-white"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2 font-bold text-slate-900 text-sm">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs text-white">
                  {step.step_number}
                </span>
                {step.stage} — {step.action}
              </span>
              <span className="rounded-md bg-slate-200/70 px-2.5 py-0.5 text-xs font-medium text-slate-700">
                {step.persona} • {step.touchpoint}
              </span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-slate-600">
              <strong>Objectif :</strong> <FormattedText text={step.user_goal} />
            </p>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-rose-50 p-3 text-xs text-rose-900 border border-rose-100">
                <strong className="flex items-center gap-1 font-bold">
                  <span className="material-symbols-outlined text-sm text-rose-600">report_problem</span>
                  Points de friction :
                </strong>
                <ul className="mt-1.5 list-disc pl-4 space-y-1">
                  {step.pain_points.map((p, i) => (
                    <li key={i}>
                      <FormattedText text={p} />
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-lg bg-emerald-50 p-3 text-xs text-emerald-900 border border-emerald-100">
                <strong className="flex items-center gap-1 font-bold">
                  <span className="material-symbols-outlined text-sm text-emerald-600">tips_and_updates</span>
                  Opportunités d'optimisation :
                </strong>
                <ul className="mt-1.5 list-disc pl-4 space-y-1">
                  {step.opportunities.map((o, i) => (
                    <li key={i}>
                      <FormattedText text={o} />
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <SourceBadges sources={step.sources} onSelectSource={onSelectSource} />
          </div>
        ))}
      </div>
    </section>
  </div>
);

/* ==============================================================================
 * MODE 4 : SYNTHÈSE DE NOTES EN VRAC
 * ============================================================================== */
const RawNotesView: React.FC<{
  data: RawNotesResult;
  onSelectSource: (s: SourceReference) => void;
}> = ({ data, onSelectSource }) => (
  <div className="space-y-6">
    <section className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-5 text-sm text-indigo-950">
      <strong>Bilan de dé-duplication & regroupement :</strong>{' '}
      <FormattedText text={data.deduplication_summary} />
    </section>

    {data.clusters.map((cluster, idx) => (
      <section key={idx} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
          <h2 className="text-base font-bold text-slate-900">{cluster.pillar}</h2>
          <div className="flex gap-1.5">
            {cluster.tags.map((t, i) => (
              <span
                key={i}
                className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">
          <FormattedText text={cluster.summary} />
        </p>

        <div className="mt-4 space-y-3">
          {cluster.consolidated_ideas.map((idea, i) => (
            <div key={i} className="rounded-xl border border-slate-100 bg-slate-50/70 p-4">
              <div className="flex items-center justify-between">
                <h3 className="font-bold text-slate-900 text-sm">{idea.title}</h3>
                {idea.merged_count > 1 && (
                  <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-700">
                    {idea.merged_count} notes fusionnées
                  </span>
                )}
              </div>
              <p className="mt-2 text-xs leading-relaxed text-slate-700">
                <FormattedText text={idea.structured_content} />
              </p>
              <SourceBadges sources={idea.sources} onSelectSource={onSelectSource} />
            </div>
          ))}
        </div>
      </section>
    ))}

    {data.suggested_next_steps && data.suggested_next_steps.length > 0 && (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
          <span className="material-symbols-outlined text-indigo-600">rocket_launch</span>
          Prochaines Étapes Suggérées
        </h2>
        <div className="mt-4 space-y-3">
          {data.suggested_next_steps.map((step, idx) => (
            <div key={idx} className="rounded-xl border border-slate-100 p-4 transition hover:bg-slate-50/50">
              <div className="flex items-center justify-between">
                <span className="font-bold text-slate-900 text-xs">
                  <FormattedText text={step.action} />
                </span>
                <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                  {step.category} • Impact {step.impact}
                </span>
              </div>
              <SourceBadges sources={step.sources} onSelectSource={onSelectSource} />
            </div>
          ))}
        </div>
      </section>
    )}
  </div>
);
