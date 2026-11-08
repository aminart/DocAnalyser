import React, { useEffect, useRef, useState } from 'react';
import { analysisApi } from './api';
import { SourcePanel } from './SourcePanel';
import { Analysis, Question, SourceRef, SourceRequest } from './types';
import { Icons, shortDocName } from './ui';

const CITATION = /\[\[([^[\]|]+?)\s*\|\s*([^[\]]+?)\]\]/g;
const POLL_MS = 700;

/** Texte sans les citations, pour surligner le propos dans le panneau « Source ». */
const plain = (text: string) => text.replace(CITATION, '').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();

/** Réponse en cours d'écriture : une citation pas encore fermée n'est pas affichée. */
const settled = (text: string) => text.replace(/\[\[[^\]]*$/, '');

/** Suggestions de départ : une question par grand thème (ou étape) de la synthèse. */
export const suggestionsFor = (analysis: Analysis): string[] => {
  const r = analysis.result;
  const names =
    r?.kind === 'journey' ? r.phases.map((p) => p.name) : r?.kind === 'themes' ? r.themes.map((t) => t.title) : [];
  const out = names.slice(0, 3).map((n) => `Que disent les documents sur « ${n} » ?`);
  out.push(r?.kind === 'journey' ? 'Quelles sont les principales frictions évoquées ?' : 'Sur quels points les documents divergent-ils ?');
  return out;
};

const SourceChip: React.FC<{ source: SourceRef; onOpen: () => void }> = ({ source, onOpen }) => (
  <button
    type="button"
    onClick={onOpen}
    title={
      source.found === false
        ? `Repère « ${source.location} » introuvable dans ${source.document} : cliquer pour voir le passage le plus proche`
        : `Voir le passage d'origine : ${source.document} — ${source.location}`
    }
    className={`mx-0.5 inline-flex items-center gap-[5px] rounded-md border px-2 py-0 align-baseline text-xs transition hover:border-accent hover:text-accent-ink ${
      source.found === false ? 'border-dashed border-warning bg-surface text-warning-text' : 'border-line bg-bg text-ink-muted'
    }`}
  >
    <Icons.file size={12} />
    {[shortDocName(source.document), source.location].filter(Boolean).join(' ')}
  </button>
);

/** Une ligne de réponse : **gras** et citations [[document | repère]] cliquables. */
const Inline: React.FC<{ text: string; sources: SourceRef[]; onSource: (r: SourceRequest) => void }> = ({
  text,
  sources,
  onSource,
}) => {
  const parts: React.ReactNode[] = [];
  let last = 0;
  const bold = (chunk: string, key: string) =>
    chunk.split(/(\*\*[^*]+\*\*)/g).map((b, i) =>
      b.startsWith('**') && b.endsWith('**') && b.length > 4 ? <strong key={`${key}-${i}`}>{b.slice(2, -2)}</strong> : b,
    );
  for (const m of text.matchAll(CITATION)) {
    const idx = m.index ?? 0;
    parts.push(...bold(text.slice(last, idx), `t${idx}`));
    const doc = m[1].trim();
    const loc = m[2].trim();
    const known = sources.find((s) => s.location === loc && (s.document === doc || shortDocName(s.document) === shortDocName(doc)));
    const source: SourceRef = known ?? { document: doc, location: loc };
    parts.push(
      <SourceChip
        key={`c${idx}`}
        source={source}
        onOpen={() => onSource({ document: source.document, location: source.location, text: plain(text) })}
      />,
    );
    last = idx + m[0].length;
  }
  parts.push(...bold(text.slice(last), 'end'));
  return <>{parts}</>;
};

/** Rendu Markdown minimal de la réponse : paragraphes et listes à puces. */
export const Answer: React.FC<{ text: string; sources: SourceRef[]; onSource: (r: SourceRequest) => void }> = ({
  text,
  sources,
  onSource,
}) => {
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (!list.length) return;
    const items = list;
    list = [];
    blocks.push(
      <ul key={`ul${blocks.length}`} className="m-0 flex list-disc flex-col gap-1.5 pl-5">
        {items.map((it, i) => (
          <li key={i}>
            <Inline text={it} sources={sources} onSource={onSource} />
          </li>
        ))}
      </ul>,
    );
  };
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/) || line.match(/^\d+[.)]\s+(.*)$/);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flush();
    if (line) {
      blocks.push(
        <p key={`p${blocks.length}`} className="m-0">
          <Inline text={line.replace(/^#+\s*/, '')} sources={sources} onSource={onSource} />
        </p>,
      );
    }
  }
  flush();
  return <div className="flex flex-col gap-3 text-[16px] leading-[1.6] text-ink-body">{blocks}</div>;
};

const scopeNote = (q: Question) => {
  if (q.scope === 'full') return 'Réponse fondée sur l’ensemble des documents.';
  if (q.scope === 'search') {
    const words = q.keywords.length ? ` (mots-clés : ${q.keywords.slice(0, 6).join(', ')})` : '';
    return q.passages
      ? `Réponse fondée sur ${q.passages} passage${q.passages > 1 ? 's' : ''} retrouvé${q.passages > 1 ? 's' : ''} par la recherche${words}.`
      : `Aucun passage retrouvé par la recherche${words}.`;
  }
  return '';
};

export const QuestionsPanel: React.FC<{ analysis: Analysis; onCount?: (n: number) => void }> = ({ analysis, onCount }) => {
  const [questions, setQuestions] = useState<Question[]>(analysis.questions ?? []);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [source, setSource] = useState<SourceRequest | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const running = questions.some((q) => q.status === 'running');

  useEffect(() => {
    let stopped = false;
    analysisApi
      .listQuestions(analysis.id)
      .then((qs) => !stopped && setQuestions(qs))
      .catch(() => undefined);
    return () => {
      stopped = true;
    };
  }, [analysis.id]);

  // Suivi de la réponse en cours : elle s'écrit au fil de l'eau côté serveur.
  useEffect(() => {
    if (!running) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const qs = await analysisApi.listQuestions(analysis.id);
        if (!stopped) setQuestions(qs);
      } catch {
        /* nouvel essai au prochain tour */
      }
    }, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [analysis.id, running]);

  useEffect(() => {
    onCount?.(questions.length);
  }, [questions.length, onCount]);

  const lastAnswer = questions[questions.length - 1]?.answer;
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [questions.length, lastAnswer]);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || running || sending) return;
    setSending(true);
    setError(null);
    try {
      const item = await analysisApi.askQuestion(analysis.id, question);
      setQuestions((qs) => [...qs, item]);
      setDraft('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'La question n’a pas pu être envoyée.');
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const clear = async () => {
    try {
      await analysisApi.clearQuestions(analysis.id);
      setQuestions([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible d’effacer les questions.');
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      ask(draft);
    }
  };

  return (
    <main className="mx-auto box-border flex max-w-[860px] flex-col gap-6 px-4 pb-24 sm:px-8 pt-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="m-0 text-[22px] font-bold">Questions sur les documents</h2>
          <p className="m-0 text-[15px] text-ink-muted">
            Les réponses s’appuient uniquement sur les {analysis.documents.length > 1 ? `${analysis.documents.length} documents` : 'documents'}{' '}
            de cette analyse, avec leurs sources. Cliquez sur une source pour vérifier le passage d’origine.
          </p>
        </div>
        {questions.length > 0 && (
          <button
            type="button"
            onClick={clear}
            disabled={running}
            className="min-h-11 rounded-[10px] border border-line-strong bg-surface px-4 font-semibold text-ink hover:bg-bg disabled:opacity-50"
          >
            Effacer les questions
          </button>
        )}
      </div>

      {questions.length === 0 && (
        <div className="flex flex-col gap-2.5">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-body">Pour commencer</span>
          <div className="flex flex-wrap gap-2">
            {suggestionsFor(analysis).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => ask(s)}
                className="rounded-full border border-line bg-surface px-3.5 py-2 text-left text-sm text-ink hover:border-accent hover:text-accent-ink"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <ol aria-live="polite" className="m-0 flex list-none flex-col gap-5 p-0">
        {questions.map((q) => (
          <li key={q.id} className="flex flex-col gap-3">
            <div className="self-end rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-[15px] font-medium text-accent-ink">
              {q.question}
            </div>
            <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface px-6 py-5">
              {q.answer ? (
                <Answer text={q.status === 'running' ? settled(q.answer) : q.answer} sources={q.sources} onSource={setSource} />
              ) : q.status === 'running' ? (
                <div className="flex flex-col gap-2" aria-label="Recherche dans les documents">
                  <span className="text-sm text-ink-muted">Recherche dans les documents…</span>
                  <div className="ad-shimmer h-16 rounded-lg" />
                </div>
              ) : null}
              {q.status === 'failed' && (
                <p role="alert" className="m-0 text-sm text-danger-text">
                  {q.error || 'La réponse n’a pas pu être rédigée.'}
                </p>
              )}
              {q.status === 'done' && (
                <span className="text-xs text-ink-muted">
                  {scopeNote(q)} {q.model_name}
                  {q.sources.some((s) => s.found === false) && ' · Une source citée est introuvable : vérifiez ce point.'}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>
      <div ref={endRef} />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(draft);
        }}
        className="sticky bottom-4 flex items-end gap-2 rounded-2xl border border-line-strong bg-surface p-2 shadow-lg"
      >
        <label htmlFor="question-input" className="sr-only">
          Votre question
        </label>
        <textarea
          id="question-input"
          ref={inputRef}
          rows={1}
          value={draft}
          maxLength={2000}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Votre question…"
          className="max-h-40 min-h-11 flex-grow resize-none border-none bg-transparent px-3 py-2.5 text-[15px] text-ink outline-none"
        />
        <button
          type="submit"
          disabled={!draft.trim() || running || sending}
          className="inline-flex min-h-11 items-center gap-2 rounded-[10px] border-none bg-primary px-4 font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          Envoyer
          <Icons.arrow size={16} />
        </button>
      </form>
      {error && (
        <p role="alert" className="m-0 text-sm text-danger-text">
          {error}
        </p>
      )}
      <p className="m-0 text-center text-[13px] text-ink-muted">
        Réponses générées par un modèle de langage à partir des documents : vérifiez les points importants dans les sources.
      </p>

      <SourcePanel analysisId={analysis.id} request={source} onClose={() => setSource(null)} />
    </main>
  );
};
