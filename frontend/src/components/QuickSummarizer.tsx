import React, { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown, { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

type Provider = 'gemini' | 'mistral';
type Mode = 'global_summary' | 'transcript_summary' | 'user_journey' | 'raw_notes';
type Level = 'flash' | 'standard' | 'detaille';

interface ProviderConfig {
  id: Provider;
  model: string;
  configured: boolean;
}

interface SummarizeResponse {
  summary: string;
  provider: Provider;
  model: string;
  mode: Mode;
  level: Level;
}

const API_ROOT = (import.meta.env.VITE_SUMMARIZE_URL || 'http://localhost:8000/api/summarize').replace(
  /\/$/,
  '',
);

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: 'global_summary', label: 'Synthèse globale', hint: 'Rapports, notices, documents longs' },
  { id: 'transcript_summary', label: 'Réunion', hint: 'Décisions, actions, points ouverts' },
  { id: 'user_journey', label: 'Parcours utilisateur', hint: 'Personas, étapes, irritants' },
  { id: 'raw_notes', label: 'Notes en vrac', hint: 'Regroupement par thèmes' },
];

const LEVELS: { id: Level; label: string; hint: string }[] = [
  { id: 'flash', label: 'Flash', hint: '≈ 150 mots' },
  { id: 'standard', label: 'Standard', hint: '≈ 500 mots' },
  { id: 'detaille', label: 'Détaillé', hint: '≈ 1000+ mots' },
];

const PROVIDER_LABEL: Record<Provider, string> = { gemini: 'Gemini', mistral: 'Mistral' };

/* Rendu Markdown sobre : titres courts, puces, tableaux lisibles. */
const mdComponents: Components = {
  h2: ({ children }) => (
    <h2 className="mb-3 mt-8 border-b border-slate-200 pb-2 text-lg font-bold text-slate-900 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => <h3 className="mb-2 mt-5 text-base font-semibold text-slate-800">{children}</h3>,
  p: ({ children }) => <p className="my-3 leading-relaxed text-slate-700">{children}</p>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1.5 pl-6 text-slate-700 marker:text-indigo-400">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-6 text-slate-700">{children}</ol>,
  strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full border-collapse text-left text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-slate-50 text-slate-700">{children}</thead>,
  th: ({ children }) => <th className="border-b border-slate-200 px-3 py-2 font-semibold">{children}</th>,
  td: ({ children }) => <td className="border-t border-slate-100 px-3 py-2 align-top text-slate-700">{children}</td>,
};

const formatSize = (bytes: number) =>
  bytes > 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} Mo` : `${Math.max(1, Math.round(bytes / 1024))} Ko`;

const OptionCard: React.FC<{
  id: string;
  selected: boolean;
  label: string;
  hint: string;
  onClick: () => void;
}> = ({ id, selected, label, hint, onClick }) => (
  <button
    id={id}
    type="button"
    role="radio"
    aria-checked={selected}
    onClick={onClick}
    className={`rounded-xl border px-4 py-3 text-left transition ${
      selected
        ? 'border-indigo-600 bg-indigo-50 ring-1 ring-indigo-600'
        : 'border-slate-200 bg-white hover:border-slate-300'
    }`}
  >
    <span className={`block text-sm font-semibold ${selected ? 'text-indigo-700' : 'text-slate-800'}`}>{label}</span>
    <span className="block text-xs text-slate-500">{hint}</span>
  </button>
);

export const QuickSummarizer: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState<Mode>('global_summary');
  const [level, setLevel] = useState<Level>('standard');
  const [provider, setProvider] = useState<Provider>('gemini');
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SummarizeResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${API_ROOT}/config`)
      .then((r) => r.json())
      .then((c: ProviderConfig[]) => {
        setConfigs(c);
        const firstReady = c.find((x) => x.configured);
        if (firstReady) setProvider(firstReady.id);
      })
      .catch(() => setConfigs([]));
  }, []);

  const addFiles = useCallback((list: FileList | null) => {
    if (!list) return;
    setFiles((prev) => {
      const known = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...Array.from(list).filter((f) => !known.has(`${f.name}:${f.size}`))];
    });
  }, []);

  const activeConfig = configs.find((c) => c.id === provider);

  const handleSubmit = async () => {
    if (!files.length) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      files.forEach((f) => form.append('files', f));
      form.append('provider', provider);
      form.append('mode', mode);
      form.append('level', level);
      const res = await fetch(API_ROOT, { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Erreur HTTP ${res.status}`);
      setResult(data as SummarizeResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur inconnue');
    } finally {
      setLoading(false);
    }
  };

  const copySummary = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      {/* ---------- Paramètres ---------- */}
      <section className="space-y-6 self-start rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">1. Documents</h2>
          <div
            id="dropzone"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
            className={`cursor-pointer rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${
              dragging ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 hover:border-slate-400'
            }`}
          >
            <p className="text-sm font-medium text-slate-700">Glissez vos fichiers ici ou cliquez pour parcourir</p>
            <p className="mt-1 text-xs text-slate-500">PDF, Word, PowerPoint, Excel, CSV, TXT, Markdown, VTT/SRT</p>
            <input
              ref={inputRef}
              id="file-input"
              type="file"
              multiple
              accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.vtt,.srt"
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </div>

          {files.length > 0 && (
            <ul className="mt-3 divide-y divide-slate-100 rounded-lg border border-slate-200">
              {files.map((f) => (
                <li key={`${f.name}:${f.size}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                  <span className="truncate text-slate-700">{f.name}</span>
                  <span className="flex shrink-0 items-center gap-3 text-xs text-slate-500">
                    {formatSize(f.size)}
                    <button
                      type="button"
                      aria-label={`Retirer ${f.name}`}
                      onClick={() => setFiles((prev) => prev.filter((x) => x !== f))}
                      className="text-slate-400 hover:text-rose-600"
                    >
                      ✕
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">2. Mode d'analyse</h2>
          <div role="radiogroup" aria-label="Mode d'analyse" className="grid grid-cols-2 gap-2">
            {MODES.map((m) => (
              <OptionCard key={m.id} id={`mode-${m.id}`} selected={mode === m.id} label={m.label} hint={m.hint} onClick={() => setMode(m.id)} />
            ))}
          </div>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">3. Niveau de synthèse</h2>
          <div role="radiogroup" aria-label="Niveau de synthèse" className="grid grid-cols-3 gap-2">
            {LEVELS.map((l) => (
              <OptionCard key={l.id} id={`level-${l.id}`} selected={level === l.id} label={l.label} hint={l.hint} onClick={() => setLevel(l.id)} />
            ))}
          </div>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">4. Modèle</h2>
          <div role="radiogroup" aria-label="Fournisseur" className="inline-flex rounded-lg bg-slate-100 p-1">
            {(['gemini', 'mistral'] as Provider[]).map((p) => (
              <button
                key={p}
                id={`provider-${p}`}
                type="button"
                role="radio"
                aria-checked={provider === p}
                onClick={() => setProvider(p)}
                className={`rounded-md px-4 py-1.5 text-sm font-semibold transition ${
                  provider === p ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                {PROVIDER_LABEL[p]}
              </button>
            ))}
          </div>
          <p id="selected-model" className="mt-2 flex items-center gap-2 text-sm text-slate-600">
            <span
              className={`h-2 w-2 rounded-full ${activeConfig?.configured ? 'bg-emerald-500' : 'bg-amber-500'}`}
              aria-hidden
            />
            Modèle utilisé :{' '}
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-800">
              {activeConfig?.model ?? '—'}
            </code>
          </p>
          {activeConfig && !activeConfig.configured && (
            <p className="mt-1 text-xs text-amber-700">Clé API absente dans backend/.env pour ce fournisseur.</p>
          )}
        </div>

        <button
          id="analyze-button"
          type="button"
          disabled={!files.length || loading}
          onClick={handleSubmit}
          className="w-full rounded-xl bg-indigo-600 px-5 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Analyse en cours…' : `Analyser${files.length > 1 ? ` ${files.length} documents` : ''}`}
        </button>
      </section>

      {/* ---------- Résultat ---------- */}
      <section className="min-w-0">
        {error && (
          <div role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </div>
        )}

        {loading && (
          <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-8 text-sm text-slate-600 shadow-sm">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
            Lecture des documents et génération de la synthèse avec {activeConfig?.model}…
          </div>
        )}

        {!loading && !result && !error && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white/60 p-10 text-center text-sm text-slate-500">
            La synthèse s'affichera ici après l'analyse.
          </div>
        )}

        {result && !loading && (
          <article id="result" className="rounded-2xl border border-slate-200 bg-white shadow-sm">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-8 py-4">
              <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
                <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-indigo-700">
                  {PROVIDER_LABEL[result.provider]} · {result.model}
                </span>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">
                  {MODES.find((m) => m.id === result.mode)?.label}
                </span>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">
                  {LEVELS.find((l) => l.id === result.level)?.label}
                </span>
              </div>
              <button
                id="copy-summary"
                type="button"
                onClick={copySummary}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                {copied ? 'Copié ✓' : 'Copier'}
              </button>
            </header>
            <div className="px-8 py-6 text-[15px]">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {result.summary}
              </ReactMarkdown>
            </div>
          </article>
        )}
      </section>
    </div>
  );
};
