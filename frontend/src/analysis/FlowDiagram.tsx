import React, { useEffect, useId, useState } from 'react';
import { FlowGraph } from './types';

type Direction = 'LR' | 'TB';

const LEGEND: { label: string; swatch: React.CSSProperties }[] = [
  { label: 'Entrée / objectif', swatch: { borderRadius: 999, border: '1.5px solid var(--nn-ink)' } },
  { label: 'Étape', swatch: { borderRadius: 3, border: '1.5px solid var(--nn-line-strong)' } },
  { label: 'Décision', swatch: { transform: 'rotate(45deg) scale(0.8)', border: '1.5px solid var(--nn-ink-muted)', background: 'var(--nn-bg)' } },
  { label: 'Point de friction', swatch: { borderRadius: 3, border: '2px solid var(--nn-warning)', background: 'var(--nn-warning-soft)' } },
  { label: 'Abandon / sortie', swatch: { borderRadius: 3, border: '1.5px dashed var(--nn-warning)' } },
];

const EDGE_LEGEND = [
  { label: 'Chemin principal', stroke: 'var(--nn-ink-muted)', dash: undefined },
  { label: 'Alternatif', stroke: 'var(--nn-ink-subtle)', dash: undefined },
  { label: 'Vers un abandon', stroke: 'var(--nn-warning)', dash: '4 3' },
  { label: 'Retour en arrière', stroke: 'var(--nn-primary)', dash: '2 3' },
];

let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;

/** Mermaid n'est téléchargé qu'au premier rapport de parcours affiché. */
const loadMermaid = () => {
  mermaidPromise ??= import('mermaid').then(({ default: mermaid }) => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      themeVariables: {
        fontFamily: '"Schibsted Grotesk", system-ui, sans-serif',
        fontSize: '14px',
        primaryTextColor: '#15171C',
        lineColor: '#5A6070',
        edgeLabelBackground: '#FFFFFF',
      },
      flowchart: { curve: 'basis', htmlLabels: true, useMaxWidth: false, nodeSpacing: 36, rankSpacing: 48, padding: 12 },
    });
    return mermaid;
  });
  return mermaidPromise;
};

export const FlowDiagram: React.FC<{ graph: FlowGraph }> = ({ graph }) => {
  const initial: Direction = graph.mermaid.startsWith('flowchart TB') ? 'TB' : 'LR';
  const [direction, setDirection] = useState<Direction>(initial);
  const [zoom, setZoom] = useState(1);
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const renderId = `flow-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    const source = graph.mermaid.replace(/^flowchart (LR|TB)/, `flowchart ${direction}`);
    loadMermaid()
      .then((mermaid) => mermaid.render(`${renderId}-${direction}`, source))
      .then(({ svg: out }) => !cancelled && setSvg(out))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [graph.mermaid, direction, renderId]);

  const labels = Object.fromEntries(graph.nodes.map((n) => [n.id, n.label]));
  const btn = (on: boolean) =>
    `min-h-8 rounded-md border-none px-3 text-[13px] font-semibold ${
      on ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(20,23,31,0.12)]' : 'bg-transparent text-ink-body'
    }`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Orientation du schéma" className="flex gap-0.5 rounded-lg bg-surface-3 p-[3px]">
          <button type="button" aria-pressed={direction === 'LR'} onClick={() => setDirection('LR')} className={btn(direction === 'LR')}>
            Horizontal
          </button>
          <button type="button" aria-pressed={direction === 'TB'} onClick={() => setDirection('TB')} className={btn(direction === 'TB')}>
            Vertical
          </button>
        </div>
        <div role="group" aria-label="Zoom" className="flex items-center gap-0.5 rounded-lg bg-surface-3 p-[3px]">
          <button type="button" aria-label="Dézoomer" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.2).toFixed(1)))} className={`${btn(false)} w-8 px-0`}>
            −
          </button>
          <button type="button" onClick={() => setZoom(1)} className={`${btn(false)} min-w-[52px] tabular-nums`} title="Taille réelle">
            {Math.round(zoom * 100)} %
          </button>
          <button type="button" aria-label="Zoomer" onClick={() => setZoom((z) => Math.min(2, +(z + 0.2).toFixed(1)))} className={`${btn(false)} w-8 px-0`}>
            +
          </button>
        </div>
        <span className="text-[13px] text-ink-muted">
          {graph.nodes.length} étapes · {graph.edges.length} liens
        </span>
      </div>

      <div className="max-h-[720px] overflow-auto rounded-xl border border-line bg-[#FFFFFF] p-4">
        {failed ? (
          <ol className="m-0 flex flex-col gap-1.5 pl-5 text-sm text-ink-body">
            {graph.edges.map((e, i) => (
              <li key={i}>
                {labels[e.from]} → {labels[e.to]}
                {e.label && <span className="text-ink-muted"> — {e.label}</span>}
              </li>
            ))}
          </ol>
        ) : svg ? (
          <div
            role="img"
            aria-label={`Schéma du parcours : ${graph.nodes.map((n) => n.label).join(', ')}`}
            className="w-max [&_svg]:max-w-none"
            style={{ zoom }}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ) : (
          <div className="ad-shimmer h-48 rounded-lg" aria-label="Chargement du schéma" />
        )}
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-ink-body">
        {LEGEND.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-2">
            <span className="inline-block h-3 w-4 bg-surface" style={l.swatch} />
            {l.label}
          </span>
        ))}
        {EDGE_LEGEND.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-2">
            <svg width="22" height="8" aria-hidden="true">
              <line x1="1" y1="4" x2="21" y2="4" stroke={l.stroke} strokeWidth="2" strokeDasharray={l.dash} />
            </svg>
            {l.label}
          </span>
        ))}
      </div>
    </div>
  );
};
