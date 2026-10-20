import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  securityLevel: 'loose',
  themeVariables: {
    primaryColor: '#eef2ff',
    primaryTextColor: '#1e1b4b',
    primaryBorderColor: '#6366f1',
    lineColor: '#4f46e5',
    secondaryColor: '#f8fafc',
    tertiaryColor: '#ffffff',
  },
});

interface MermaidViewerProps {
  chart: string;
}

export const MermaidViewer: React.FC<MermaidViewerProps> = ({ chart }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svgContent, setSvgContent] = useState<string>('');
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const renderDiagram = async () => {
      if (!chart.trim()) return;
      try {
        const id = `mermaid-${Math.random().toString(36).substring(2, 9)}`;
        const { svg } = await mermaid.render(id, chart);
        if (isMounted) {
          setSvgContent(svg);
        }
      } catch (err) {
        console.warn('Mermaid fallback to code view:', err);
        if (isMounted) {
          setShowRaw(true);
        }
      }
    };
    renderDiagram();
    return () => {
      isMounted = false;
    };
  }, [chart]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 pb-4">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-indigo-600">account_tree</span>
          <h3 className="font-bold text-slate-900">
            Modélisation Visuelle du Flux (Mermaid.js)
          </h3>
        </div>
        <button
          type="button"
          onClick={() => setShowRaw((prev) => !prev)}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          <span className="material-symbols-outlined text-sm">code</span>
          {showRaw ? 'Voir le diagramme' : 'Voir le code Mermaid'}
        </button>
      </div>

      {showRaw || !svgContent ? (
        <pre className="mt-4 overflow-x-auto rounded-xl bg-slate-900 p-4 font-mono text-xs text-slate-100">
          {chart}
        </pre>
      ) : (
        <div
          ref={containerRef}
          className="mt-4 flex justify-center overflow-x-auto rounded-xl bg-slate-50/70 p-6"
          dangerouslySetInnerHTML={{ __html: svgContent }}
        />
      )}
    </div>
  );
};
