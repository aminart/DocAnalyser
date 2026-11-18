import React, { useEffect, useState } from 'react';
import { analysisApi } from './api';
import { Analysis } from './types';

/** Modification du texte de la synthèse avant export (Markdown, Word, PDF). */
export const MarkdownEditor: React.FC<{ analysis: Analysis; onSaved: (a: Analysis) => void }> = ({ analysis, onSaved }) => {
  const [text, setText] = useState(analysis.markdown);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ tone: 'ok' | 'error'; msg: string } | null>(null);

  useEffect(() => setText(analysis.markdown), [analysis.id, analysis.markdown]);

  const changed = text !== analysis.markdown;

  const save = async (markdown: string | null) => {
    setBusy(true);
    setStatus(null);
    try {
      const updated = await analysisApi.updateMarkdown(analysis.id, markdown);
      onSaved(updated);
      setText(updated.markdown);
      setStatus({ tone: 'ok', msg: markdown === null ? 'Texte d’origine rétabli.' : 'Modifications enregistrées.' });
    } catch (e) {
      setStatus({ tone: 'error', msg: e instanceof Error ? e.message : 'Enregistrement impossible.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto box-border flex max-w-[1080px] flex-col gap-4 px-8 pb-16 pt-8">
      <p className="m-0 text-sm text-ink-muted">
        Corrigez ici le texte de la synthèse avant de l’exporter : les exports Markdown, Word et PDF reprennent ce texte.
        La synthèse affichée dans l’onglet « Synthèse » ne change pas. Mise en forme : <code># Titre</code>,{' '}
        <code>## Sous-titre</code>, <code>- élément de liste</code>, <code>**gras**</code>.
      </p>
      <label htmlFor="md-text" className="sr-only">
        Texte de la synthèse
      </label>
      <textarea
        id="md-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck
        className="box-border min-h-[60vh] w-full resize-y rounded-xl border border-line-strong bg-surface p-4 font-mono text-sm leading-relaxed text-ink"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={!changed || busy}
          onClick={() => save(text)}
          className="inline-flex min-h-11 items-center rounded-[10px] border-none bg-primary px-5 font-semibold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          Enregistrer
        </button>
        {changed && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setText(analysis.markdown)}
            className="inline-flex min-h-11 items-center rounded-[10px] border border-line-strong bg-surface px-5 font-semibold text-ink hover:bg-bg"
          >
            Annuler les modifications
          </button>
        )}
        {analysis.markdown_edited && !changed && (
          <button
            type="button"
            disabled={busy}
            onClick={() => save(null)}
            className="inline-flex min-h-11 items-center rounded-[10px] border border-line-strong bg-surface px-5 font-semibold text-ink hover:bg-bg"
          >
            Revenir au texte d’origine
          </button>
        )}
        {status && (
          <span role="status" className={`text-sm ${status.tone === 'ok' ? 'text-success-text' : 'text-danger-text'}`}>
            {status.msg}
          </span>
        )}
      </div>
    </main>
  );
};
