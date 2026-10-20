import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { analysisApi } from './api';
import { Analysis, AnalysisLevel, AnalysisMode, ModelInfo, UploadedDocument } from './types';
import { FileBadge, Icons, extOf, formatSize } from './ui';

interface FileEntry {
  key: string;
  name: string;
  ext: string;
  size: number;
  status: 'uploading' | 'ready' | 'error';
  doc?: UploadedDocument;
  error?: string;
}

export const MODES: {
  id: AnalysisMode;
  title: string;
  desc: string;
  ideal: string;
  Icon: (typeof Icons)[keyof typeof Icons];
}[] = [
  {
    id: 'global',
    title: 'Synthèse globale',
    desc: 'Croise l’ensemble des documents pour dégager les grands thèmes, les convergences et les points de divergence.',
    ideal: 'études, rapports, corpus hétérogènes',
    Icon: Icons.modeGlobal,
  },
  {
    id: 'transcript',
    title: 'Synthèse de transcription',
    desc: 'Extrait idées clés, décisions et verbatims marquants d’un entretien, d’une réunion ou d’un atelier.',
    ideal: 'interviews, comités, ateliers',
    Icon: Icons.modeTranscript,
  },
  {
    id: 'notes',
    title: 'Synthèse de notes en vrac',
    desc: 'Remet de l’ordre dans des notes brutes, post-its ou comptes rendus épars en les regroupant par thème.',
    ideal: 'notes de terrain, brainstorms',
    Icon: Icons.modeNotes,
  },
  {
    id: 'flow',
    title: 'Flux et parcours utilisateurs',
    desc: 'Reconstitue les étapes d’un parcours, ses points de friction, ses irritants et les opportunités.',
    ideal: 'recherche UX, parcours client',
    Icon: Icons.modeFlow,
  },
];

export const LEVELS: { id: AnalysisLevel; title: string; desc: string; bars: number; minutes: number }[] = [
  { id: 'synth', title: 'Synthétique', desc: 'Tous les thèmes, rédigés à l’essentiel : une phrase par point clé.', bars: 3, minutes: 1 },
  { id: 'detail', title: 'Détaillé', desc: 'Chaque point développé avec un exemple et un verbatim par thème.', bars: 5, minutes: 2 },
  { id: 'deep', title: 'Très détaillé', desc: 'Points argumentés et décomposés, nuances et sources pour chacun.', bars: 7, minutes: 4 },
];

const BAR_WIDTHS = ['100%', '80%', '92%', '64%', '100%', '76%', '88%'];
const TIER_FOR_LEVEL: Record<AnalysisLevel, ModelInfo['tier']> = { synth: 'fast', detail: 'balanced', deep: 'deep' };
const ACCEPT = '.pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.vtt,.srt';

const SectionTitle: React.FC<{ n: number; id: string; children: React.ReactNode; right?: React.ReactNode }> = ({
  n,
  id,
  children,
  right,
}) => (
  <div className="mb-5 flex flex-wrap items-center gap-3">
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ink text-[13px] font-bold text-white">
      {n}
    </span>
    <h2 id={id} className="m-0 text-[19px] font-bold">
      {children}
    </h2>
    {right && <span className="ml-auto text-sm text-muted">{right}</span>}
  </div>
);

const Radio: React.FC<{ on: boolean }> = ({ on }) => (
  <span
    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${
      on ? 'border-accent' : 'border-[#B9C0CF]'
    }`}
  >
    <span className={`h-2.5 w-2.5 rounded-full ${on ? 'bg-accent' : 'bg-transparent'}`} />
  </span>
);

const optionClass = (on: boolean, disabled = false) =>
  `rounded-xl border-[1.5px] text-left text-ink transition ${
    on ? 'border-accent bg-accent-soft' : 'border-line bg-white hover:border-line-strong'
  } ${disabled ? 'cursor-not-allowed opacity-60 hover:border-line' : ''}`;

const Dots: React.FC<{ label: string; value: number; on: boolean }> = ({ label, value, on }) => (
  <span className="flex flex-col gap-[5px]">
    <span className="text-xs text-muted">{label}</span>
    <span className="flex gap-[3px]" aria-label={`${label} ${value} sur 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className="h-1.5 w-3.5 rounded-[3px]"
          style={{ background: i <= value ? (on ? 'var(--ad-accent)' : 'var(--ad-muted)') : 'var(--ad-line)' }}
        />
      ))}
    </span>
  </span>
);

export const ConfigScreen: React.FC<{ onLaunched: (analysis: Analysis) => void }> = ({ onLaunched }) => {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [mode, setMode] = useState<AnalysisMode>('global');
  const [level, setLevel] = useState<AnalysisLevel>('detail');
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [pickedModel, setPickedModel] = useState<string | null>(null);
  const [showAllModels, setShowAllModels] = useState(false);
  const [language, setLanguage] = useState<'fr' | 'en'>('fr');
  const [cite, setCite] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    analysisApi
      .listModels()
      .then(setModels)
      .catch((e: Error) => setModelsError(e.message));
  }, []);

  const addFiles = useCallback((list: FileList | null) => {
    if (!list) return;
    Array.from(list).forEach((file) => {
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      setFiles((prev) => {
        if (prev.some((f) => f.key === key)) return prev;
        return [...prev, { key, name: file.name, ext: extOf(file.name), size: file.size, status: 'uploading' }];
      });
      analysisApi
        .uploadDocument(file)
        .then((doc) =>
          setFiles((prev) => prev.map((f) => (f.key === key ? { ...f, status: 'ready', doc } : f))),
        )
        .catch((e: Error) =>
          setFiles((prev) => prev.map((f) => (f.key === key ? { ...f, status: 'error', error: e.message } : f))),
        );
    });
  }, []);

  const removeFile = (entry: FileEntry) => {
    if (entry.doc) analysisApi.deleteDocument(entry.doc.id);
    setFiles((prev) => prev.filter((f) => f.key !== entry.key));
  };

  const configured = models.filter((m) => m.configured);
  const recommended = useMemo(() => {
    const tier = TIER_FOR_LEVEL[level];
    return configured.find((m) => m.tier === tier) ?? configured.find((m) => m.tier === 'balanced') ?? configured[0];
  }, [configured, level]);
  // Tant que l'utilisateur n'a pas choisi, on suit la recommandation.
  const selectedModel = models.find((m) => m.id === pickedModel && m.configured) ?? recommended;

  const visibleModels = showAllModels ? models : configured;
  const hiddenCount = models.length - configured.length;

  const ready = files.filter((f) => f.status === 'ready');
  const uploading = files.some((f) => f.status === 'uploading');
  const fileCountLabel = `${ready.length} fichier${ready.length > 1 ? 's' : ''}`;
  const lvl = LEVELS.find((l) => l.id === level)!;
  const totalPages = ready.reduce((n, f) => n + (f.doc?.pages ?? 0), 0);
  const eta = `≈ ${lvl.minutes + Math.floor(totalPages / 150)} min`;

  const canLaunch = ready.length > 0 && !uploading && !!selectedModel && !submitting;
  const blocker = !ready.length
    ? 'Importez au moins un document.'
    : uploading
      ? 'Lecture des documents en cours…'
      : !selectedModel
        ? 'Aucun modèle disponible : complétez backend/.env.'
        : null;

  const launch = async () => {
    if (!canLaunch || !selectedModel) return;
    setSubmitting(true);
    setError(null);
    try {
      const analysis = await analysisApi.createAnalysis({
        document_ids: ready.map((f) => f.doc!.id),
        mode,
        level,
        model_id: selectedModel.id,
        language,
        cite,
      });
      onLaunched(analysis);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible de lancer l’analyse.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="mx-auto box-border max-w-[1240px] px-8 pb-[72px] pt-10">
      <div className="mb-8 flex flex-col gap-1.5">
        <h1 className="m-0 text-[34px] font-bold leading-[1.15] tracking-[-0.02em]">Nouvelle analyse</h1>
        <p className="m-0 text-base text-muted">
          Importez vos documents, choisissez comment les lire, et laissez le modèle en dégager les grands thèmes.
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-7">
        <div className="flex min-w-0 flex-[999_1_640px] flex-col gap-5">
          {/* 1 · Documents */}
          <section aria-labelledby="s1" className="rounded-[14px] border border-line bg-white p-7">
            <SectionTitle n={1} id="s1" right={fileCountLabel}>
              Documents
            </SectionTitle>

            <label
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
              className={`relative flex cursor-pointer flex-col items-center gap-2.5 rounded-xl border-[1.5px] border-dashed px-6 py-8 text-center transition focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${
                dragging ? 'border-accent bg-accent-soft' : 'border-[#B9C0CF] bg-[#FAFBFC] hover:border-muted'
              }`}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-tint text-accent">
                <Icons.upload size={22} />
              </span>
              <span className="text-base font-semibold">
                Glissez vos documents ici, ou <span className="text-accent underline">parcourez vos fichiers</span>
              </span>
              <span className="text-[13px] text-muted">
                PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, VTT/SRT · plusieurs fichiers acceptés
              </span>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPT}
                className="absolute h-px w-px opacity-0"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = '';
                }}
              />
            </label>

            {files.length > 0 ? (
              <ul className="m-0 mt-4 flex list-none flex-col gap-2 p-0">
                {files.map((f) => (
                  <li key={f.key} className="flex items-center gap-3.5 rounded-[10px] border border-line px-3.5 py-3">
                    <FileBadge ext={f.ext} />
                    <span className="flex min-w-0 flex-grow flex-col">
                      <span className="truncate font-semibold">{f.name}</span>
                      <span className={`text-[13px] ${f.status === 'error' ? 'text-[#9B2216]' : 'text-muted'}`}>
                        {f.status === 'error'
                          ? f.error
                          : [f.ext.toUpperCase(), formatSize(f.size), f.doc?.units].filter(Boolean).join(' · ')}
                      </span>
                      {f.doc?.warnings.map((w) => (
                        <span key={w} className="text-[13px] font-medium text-[#8A3E0A]">
                          ⚠ {w}
                        </span>
                      ))}
                    </span>
                    <span
                      className={`flex shrink-0 items-center gap-1.5 text-[13px] font-semibold ${
                        f.status === 'ready' ? 'text-ok' : f.status === 'error' ? 'text-[#9B2216]' : 'text-muted'
                      }`}
                    >
                      {f.status === 'ready' && (
                        <>
                          <Icons.check size={16} strokeWidth={2.2} />
                          Prêt
                        </>
                      )}
                      {f.status === 'uploading' && (
                        <>
                          <svg className="ad-spin" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                          </svg>
                          Lecture…
                        </>
                      )}
                      {f.status === 'error' && 'Erreur'}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeFile(f)}
                      aria-label={`Retirer ${f.name}`}
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border-none bg-transparent text-muted hover:bg-page"
                    >
                      <Icons.close size={18} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 mt-3.5 text-sm text-muted">Aucun document importé pour l'instant.</p>
            )}
          </section>

          {/* 2 · Mode */}
          <section aria-labelledby="s2" className="rounded-[14px] border border-line bg-white p-7">
            <SectionTitle n={2} id="s2">
              Mode d'analyse
            </SectionTitle>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]">
              {MODES.map((m) => {
                const on = mode === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setMode(m.id)}
                    className={`flex flex-col gap-2.5 p-[18px] ${optionClass(on)}`}
                  >
                    <span className="flex w-full items-center gap-3">
                      <span
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] ${
                          on ? 'bg-accent text-white' : 'bg-chip text-chip-ink'
                        }`}
                      >
                        <m.Icon size={20} />
                      </span>
                      <span className="flex-grow text-base font-bold">{m.title}</span>
                      <Radio on={on} />
                    </span>
                    <span className="text-sm leading-normal text-body">{m.desc}</span>
                    <span className="text-[13px] text-muted">
                      <strong className="font-semibold text-ink">Idéal pour :</strong> {m.ideal}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* 3 · Niveau */}
          <section aria-labelledby="s3" className="rounded-[14px] border border-line bg-white p-7">
            <SectionTitle n={3} id="s3">
              Niveau d'analyse
            </SectionTitle>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
              {LEVELS.map((l) => {
                const on = level === l.id;
                return (
                  <button
                    key={l.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setLevel(l.id)}
                    className={`flex items-start gap-4 p-[18px] ${optionClass(on)}`}
                  >
                    <span
                      aria-hidden="true"
                      className="box-border flex h-[54px] w-11 shrink-0 flex-col gap-[3px] rounded-md border border-line bg-white px-[7px] py-2"
                    >
                      {BAR_WIDTHS.slice(0, l.bars).map((w, i) => (
                        <span
                          key={i}
                          className="h-[3px] rounded-sm"
                          style={{ width: w, background: on ? 'var(--ad-accent)' : '#C3C9D6' }}
                        />
                      ))}
                    </span>
                    <span className="flex flex-col gap-1">
                      <span className="text-base font-bold">{l.title}</span>
                      <span className="text-sm leading-[1.45] text-body">{l.desc}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* 4 · Modèle */}
          <section aria-labelledby="s4" className="rounded-[14px] border border-line bg-white p-7">
            <SectionTitle
              n={4}
              id="s4"
              right={<span className="text-[13px]">Recommandation adaptée au mode et au niveau choisis</span>}
            >
              Modèle LLM
            </SectionTitle>
            {modelsError && (
              <p role="alert" className="m-0 mb-3 text-sm text-[#9B2216]">
                {modelsError}
              </p>
            )}
            {!modelsError && models.length === 0 && (
              <p className="m-0 mb-3 text-sm text-[#8A3E0A]">
                Aucun modèle déclaré : renseignez CUSTOM_LLM_API_BASE et CUSTOM_LLM_AVAILABLE_MODELS dans backend/.env
                (voir .env.example), puis redémarrez le backend.
              </p>
            )}
            {!modelsError && models.length > 0 && configured.length === 0 && (
              <p className="m-0 mb-3 text-sm text-[#8A3E0A]">
                Les modèles sont déclarés mais aucune adresse d'API n'est renseignée : complétez CUSTOM_LLM_API_BASE
                dans backend/.env.
              </p>
            )}
            <div className="flex flex-col gap-2.5">
              {visibleModels.map((m) => {
                const on = selectedModel?.id === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    aria-pressed={on}
                    disabled={!m.configured}
                    onClick={() => setPickedModel(m.id)}
                    className={`flex flex-wrap items-center gap-x-6 gap-y-4 px-[18px] py-4 ${optionClass(on, !m.configured)}`}
                  >
                    <span className="flex min-w-0 flex-[999_1_280px] items-center gap-3.5">
                      <Radio on={on} />
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-base font-bold">{m.name}</span>
                          <span className="rounded-full border border-line-strong px-2 py-px text-xs text-body">
                            {m.provider_label}
                          </span>
                          {m.configured && m.id === recommended?.id && (
                            <span className="rounded-full bg-ok-soft px-2 py-0.5 text-xs font-semibold text-ok">
                              Recommandé
                            </span>
                          )}
                          {!m.configured && (
                            <span className="rounded-full bg-chip px-2 py-0.5 text-xs font-semibold text-chip-ink">
                              Non configuré
                            </span>
                          )}
                        </span>
                        <span className="text-sm text-body">{m.description}</span>
                      </span>
                    </span>
                    <span className="flex flex-[1_1_260px] flex-wrap justify-end gap-5">
                      <Dots label="Qualité" value={m.quality} on={on} />
                      <Dots label="Vitesse" value={m.speed} on={on} />
                      <Dots label="Économie" value={m.economy} on={on} />
                    </span>
                  </button>
                );
              })}
            </div>
            {hiddenCount > 0 && (
              <button
                type="button"
                onClick={() => setShowAllModels((v) => !v)}
                className="mt-3 border-none bg-transparent p-0 text-sm font-semibold text-accent hover:text-accent-hover"
              >
                {showAllModels
                  ? 'Masquer les modèles non configurés'
                  : `Afficher les modèles non configurés (${hiddenCount})`}
              </button>
            )}
          </section>
        </div>

        {/* Récapitulatif */}
        <aside aria-label="Récapitulatif" className="flex min-w-0 flex-[1_1_320px] flex-col gap-4 lg:sticky lg:top-6">
          <div className="flex flex-col gap-[18px] rounded-[14px] border border-line bg-white p-6">
            <h2 className="m-0 text-[17px] font-bold">Récapitulatif</h2>
            <dl className="m-0 flex flex-col gap-3.5">
              {(
                [
                  ['Documents', fileCountLabel],
                  ['Mode', MODES.find((m) => m.id === mode)!.title],
                  ['Niveau', lvl.title],
                  ['Modèle', selectedModel?.name ?? '—'],
                ] as const
              ).map(([dt, dd], i, arr) => (
                <div
                  key={dt}
                  className={`flex justify-between gap-3 ${i < arr.length - 1 ? 'border-b border-hair pb-3' : ''}`}
                >
                  <dt className="text-muted">{dt}</dt>
                  <dd className="m-0 text-right font-semibold">{dd}</dd>
                </div>
              ))}
            </dl>

            <div className="flex flex-col gap-3 rounded-[10px] bg-[#F7F8FA] px-4 py-3.5">
              <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-body">Options</span>
              <label className="flex items-center justify-between gap-3 text-sm">
                Langue de la synthèse
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value as 'fr' | 'en')}
                  className="rounded-lg border border-line-strong bg-white px-2 py-1.5 text-ink"
                >
                  <option value="fr">Français</option>
                  <option value="en">Anglais</option>
                </select>
              </label>
              <button
                type="button"
                aria-pressed={cite}
                onClick={() => setCite((c) => !c)}
                className="flex min-h-8 items-center justify-between gap-3 border-none bg-transparent p-0 text-left text-sm text-ink"
              >
                Citer les sources dans la synthèse
                <span
                  className={`box-border flex h-[22px] w-[38px] shrink-0 items-center rounded-full p-[3px] transition ${
                    cite ? 'justify-end bg-accent' : 'justify-start bg-[#C3C9D6]'
                  }`}
                >
                  <span className="h-4 w-4 rounded-full bg-white" />
                </span>
              </button>
            </div>

            {error && (
              <p role="alert" className="m-0 rounded-lg bg-[#FCE4E2] px-3 py-2 text-sm text-[#9B2216]">
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={launch}
              disabled={!canLaunch}
              className="flex min-h-[52px] items-center justify-center gap-2.5 rounded-xl border-none bg-accent text-[17px] font-bold text-white transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Lancement…' : 'Analyser'}
              <Icons.arrow size={18} strokeWidth={2.2} />
            </button>
            <p className="m-0 text-center text-[13px] text-muted">{blocker ?? `Durée estimée : ${eta}`}</p>
          </div>
        </aside>
      </div>
    </main>
  );
};
