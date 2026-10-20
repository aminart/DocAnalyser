import React, { useEffect, useRef, useState } from 'react';
import { analysisApi } from './api';
import { Analysis } from './types';

/* ---------- Icônes (traits 24×24) ---------- */

type IconProps = { size?: number; strokeWidth?: number; className?: string; style?: React.CSSProperties };

const icon =
  (paths: React.ReactNode, defaults: { strokeWidth?: number } = {}) =>
  ({ size = 18, strokeWidth, className, style }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth ?? defaults.strokeWidth ?? 2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={style}
    >
      {paths}
    </svg>
  );

export const Icons = {
  logo: icon(<path d="M4 5h11M4 10h16M4 15h9M4 20h13" />),
  upload: icon(
    <>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </>,
    { strokeWidth: 1.8 },
  ),
  check: icon(<path d="M5 12.5l4.5 4.5L19 7.5" />),
  close: icon(<path d="M6 6l12 12M18 6L6 18" />),
  arrow: icon(<path d="M5 12h14M13 6l6 6-6 6" />),
  copy: icon(
    <>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" />
    </>,
  ),
  download: icon(<path d="M12 4v11M7 10l5 5 5-5M5 20h14" />),
  chevron: icon(<path d="M6 9l6 6 6-6" />),
  file: icon(
    <>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
    </>,
  ),
  nuance: icon(
    <>
      <path d="M7 7h10M7 17h10" />
      <path d="M14 4l3 3-3 3M10 14l-3 3 3 3" />
    </>,
    { strokeWidth: 1.8 },
  ),
  modeGlobal: icon(
    <>
      <path d="M12 3l9 5-9 5-9-5 9-5z" />
      <path d="M3 13l9 5 9-5" />
    </>,
    { strokeWidth: 1.8 },
  ),
  modeTranscript: icon(
    <>
      <path d="M4 6h16v10H9l-5 4V6z" />
      <path d="M8 10h8M8 13h5" />
    </>,
    { strokeWidth: 1.8 },
  ),
  modeNotes: icon(
    <>
      <rect x="3" y="3" width="9" height="9" rx="1.5" />
      <rect x="12" y="12" width="9" height="9" rx="1.5" />
      <path d="M15 3h6v6M3 15v6h6" />
    </>,
    { strokeWidth: 1.8 },
  ),
  modeFlow: icon(
    <>
      <circle cx="5" cy="6" r="2.2" />
      <circle cx="19" cy="18" r="2.2" />
      <path d="M7.2 6H15a3.5 3.5 0 0 1 0 7H9a3.5 3.5 0 0 0 0 7h7.8" />
    </>,
    { strokeWidth: 1.8 },
  ),
};

/* ---------- Fichiers ---------- */

const EXT_COLORS: Record<string, [string, string]> = {
  pdf: ['#FDECEA', '#A3261B'],
  docx: ['#EAF0FD', '#2447B8'],
  doc: ['#EAF0FD', '#2447B8'],
  csv: ['#E6F4EF', '#0F6E55'],
  xlsx: ['#E6F4EF', '#0F6E55'],
  xls: ['#E6F4EF', '#0F6E55'],
  pptx: ['#FCEFE6', '#A04A0C'],
  ppt: ['#FCEFE6', '#A04A0C'],
  vtt: ['#F2EAFB', '#6A35AE'],
  srt: ['#F2EAFB', '#6A35AE'],
};

export const extColors = (ext: string): [string, string] => EXT_COLORS[ext.toLowerCase()] ?? ['#EEF0F3', '#3E4452'];

export const extOf = (name: string) => (name.includes('.') ? name.split('.').pop()!.toLowerCase() : 'txt');

export const formatSize = (bytes: number) =>
  bytes >= 1_048_576
    ? `${(bytes / 1_048_576).toFixed(1).replace('.', ',')} Mo`
    : `${Math.max(1, Math.round(bytes / 1024))} Ko`;

/** « Entretiens_utilisateurs_vague2.pdf » → « Entretiens utilisateurs vague2 » */
export const shortDocName = (name: string) => {
  const stem = name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
  return stem.length > 28 ? `${stem.slice(0, 26)}…` : stem;
};

export const FileBadge: React.FC<{ ext: string; size?: 'lg' | 'sm' }> = ({ ext, size = 'lg' }) => {
  const [bg, fg] = extColors(ext);
  const label = ext.toUpperCase().slice(0, 4);
  return size === 'lg' ? (
    <span
      className="flex h-11 w-[38px] shrink-0 items-end justify-center rounded-md pb-1.5 text-[10px] font-bold tracking-[0.04em]"
      style={{ background: bg, color: fg }}
    >
      {label}
    </span>
  ) : (
    <span
      className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-[5px] text-[9px] font-bold"
      style={{ background: bg, color: fg }}
    >
      {label.slice(0, 3)}
    </span>
  );
};

/* ---------- Thèmes : couleurs ---------- */

export const THEME_COLORS = [
  { soft: '#EAF0FD', ink: '#2447B8' },
  { soft: '#FCEFE6', ink: '#A04A0C' },
  { soft: '#E3F3F1', ink: '#0D6B64' },
  { soft: '#F2EAFB', ink: '#6A35AE' },
  { soft: '#FDEAF1', ink: '#A3245E' },
  { soft: '#EEF3E2', ink: '#4F6B12' },
];

export const themeColor = (index: number) => THEME_COLORS[index % THEME_COLORS.length];

/** Rend le texte en mettant en italique les passages entourés d'*astérisques*. */
export const Emphasis: React.FC<{ text: string }> = ({ text }) => (
  <>
    {text.split(/(\*[^*]+\*)/g).map((part, i) =>
      part.startsWith('*') && part.endsWith('*') && part.length > 2 ? <em key={i}>{part.slice(1, -1)}</em> : part,
    )}
  </>
);

/* ---------- En-tête ---------- */

export type View = 'new' | 'analysis';

export const AppHeader: React.FC<{
  active?: View;
  onNavigate?: (view: View) => void;
  analysisAvailable?: boolean;
  right?: React.ReactNode;
  wide?: boolean;
}> = ({ active, onNavigate, analysisAvailable, right, wide }) => (
  <header className="border-b border-line bg-white">
    <div
      className={`mx-auto flex min-h-16 flex-wrap items-center gap-6 px-8 ${wide ? 'max-w-[1280px]' : 'max-w-[1240px]'}`}
    >
      <div className="flex items-center gap-2.5 text-base font-bold">
        <div className="flex h-[30px] w-[30px] items-center justify-center rounded-lg bg-ink text-white">
          <Icons.logo size={16} />
        </div>
        <span>Analyse documentaire</span>
      </div>
      {onNavigate && (
        <nav aria-label="Navigation principale" className="flex flex-grow flex-wrap gap-1">
          {(
            [
              ['new', 'Nouvelle analyse', true],
              ['analysis', 'Analyse', analysisAvailable],
            ] as const
          ).map(([id, label, enabled]) => (
            <button
              key={id}
              type="button"
              disabled={!enabled}
              aria-current={active === id ? 'page' : undefined}
              onClick={() => onNavigate(id)}
              className={`rounded-lg border-none px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                active === id ? 'bg-accent-tint font-semibold text-accent-ink' : 'bg-transparent font-medium text-muted'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      )}
      {right && <span className="ml-auto text-sm text-muted">{right}</span>}
    </div>
  </header>
);

/* ---------- Bandeau de rapport ---------- */

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });

const ExportMenu: React.FC<{ analysisId: string }> = ({ analysisId }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex min-h-11 items-center gap-2 rounded-[10px] border border-line-strong bg-white px-4 font-semibold text-ink hover:bg-page"
      >
        <Icons.download size={17} />
        Exporter
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+6px)] z-10 flex min-w-[180px] flex-col rounded-xl border border-line bg-white p-1.5 shadow-lg"
        >
          {(
            [
              ['md', 'Markdown (.md)'],
              ['docx', 'Word (.docx)'],
              ['pdf', 'PDF (.pdf)'],
            ] as const
          ).map(([fmt, label]) => (
            <a
              key={fmt}
              role="menuitem"
              href={analysisApi.exportUrl(analysisId, fmt)}
              onClick={() => setOpen(false)}
              className="rounded-lg px-3 py-2 text-sm text-ink no-underline hover:bg-page"
            >
              {label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
};

export const ReportBanner: React.FC<{
  analysis: Analysis;
  onNewAnalysis: () => void;
  showCopy?: boolean;
  chips: string[];
  aside?: React.ReactNode;
}> = ({ analysis, onNewAnalysis, showCopy, chips, aside }) => {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(analysis.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* presse-papiers indisponible (contexte non sécurisé) */
    }
  };

  return (
    <div className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-[1280px] flex-col gap-4 px-8 pb-[22px] pt-7">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <div className="flex min-w-0 flex-[999_1_480px] flex-col gap-1.5">
            <span className="text-[13px] text-muted">Historique / {formatDate(analysis.created_at)}</span>
            <h1 className="m-0 text-[32px] font-bold leading-[1.15] tracking-[-0.02em]">{analysis.title}</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            {showCopy && (
              <button
                type="button"
                onClick={copy}
                className="inline-flex min-h-11 items-center gap-2 rounded-[10px] border border-line-strong bg-white px-4 font-semibold text-ink hover:bg-page"
              >
                {copied ? <Icons.check size={17} /> : <Icons.copy size={17} />}
                {copied ? 'Copié' : 'Copier'}
              </button>
            )}
            <ExportMenu analysisId={analysis.id} />
            <button
              type="button"
              onClick={onNewAnalysis}
              className="inline-flex min-h-11 items-center gap-2 rounded-[10px] border-none bg-ink px-4 font-semibold text-white hover:opacity-90"
            >
              Nouvelle analyse
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex flex-wrap gap-2">
            {chips.map((c, i) => (
              <span
                key={c}
                className={`rounded-full px-3 py-[5px] text-[13px] ${
                  i === 0 ? 'bg-accent-tint font-semibold text-accent-ink' : 'bg-chip text-chip-ink'
                }`}
              >
                {c}
              </span>
            ))}
          </div>
          {aside}
        </div>
      </div>
    </div>
  );
};

export const Disclaimer: React.FC = () => (
  <p className="m-0 text-center text-[13px] text-muted">
    Synthèse générée par un modèle de langage : vérifiez les points importants dans les sources citées.
  </p>
);

export const docCountLabel = (n: number) => `${n} document${n > 1 ? 's' : ''}`;

export const modelLabel = (a: Analysis) => (a.model_fallback ? `${a.model_name} (repli)` : a.model_name);
