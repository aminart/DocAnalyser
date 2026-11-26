import React, { useCallback, useEffect, useState } from 'react';
import { analysisApi } from '../analysis/api';
import { ConfigScreen, type Import } from '../analysis/ConfigScreen';
import { HistoryScreen } from '../analysis/HistoryScreen';
import { JourneyReport } from '../analysis/JourneyReport';
import { MarkdownEditor } from '../analysis/MarkdownEditor';
import { APP_TITLE, finishedTitle, notifyFinished, runningTitle } from '../analysis/notify';
import { ProgressScreen } from '../analysis/ProgressScreen';
import { QuestionsPanel } from '../analysis/QuestionsPanel';
import { SettingsScreen } from '../analysis/SettingsScreen';
import { ThemesReport } from '../analysis/ThemesReport';
import { Analysis } from '../analysis/types';
import { AppHeader, ReportBanner, ReportTab, View, docCountLabel, modelLabel } from '../analysis/ui';

type Route = { screen: 'config' | 'history' | 'settings' } | { screen: 'progress' | 'result' | 'questions' | 'text'; id: string };

const LAST_ANALYSIS_KEY = 'analyse-documentaire:last';

const parseHash = (): Route => {
  if (window.location.hash === '#/historique') return { screen: 'history' };
  if (window.location.hash === '#/reglages') return { screen: 'settings' };
  const m = window.location.hash.match(/^#\/analyse\/([\w-]+)(\/synthese|\/questions|\/texte)?$/);
  if (!m) return { screen: 'config' };
  const screen = m[2] === '/questions' ? 'questions' : m[2] === '/texte' ? 'text' : m[2] ? 'result' : 'progress';
  return { screen, id: m[1] };
};

/** #/importer/<id>?mode=transcript&from=Snappy%20Transcript : document envoyé par une autre app de la suite. */
const lireImport = (): Import | null => {
  const m = window.location.hash.match(/^#\/importer\/([\w-]+)(?:\?(.*))?$/);
  if (!m) return null;
  const p = new URLSearchParams(m[2] ?? '');
  const mode = p.get('mode');
  return { id: m[1], mode: mode === 'global' || mode === 'transcript' || mode === 'notes' || mode === 'flow' ? mode : null, from: p.get('from') ?? '' };
};

const go = (hash: string) => {
  if (window.location.hash !== hash) window.location.hash = hash;
};

const readLast = () => {
  try {
    return localStorage.getItem(LAST_ANALYSIS_KEY);
  } catch {
    return null;
  }
};

const writeLast = (id: string | null) => {
  try {
    if (id) localStorage.setItem(LAST_ANALYSIS_KEY, id);
    else localStorage.removeItem(LAST_ANALYSIS_KEY);
  } catch {
    /* stockage indisponible */
  }
};

export const App: React.FC = () => {
  const [route, setRoute] = useState<Route>(parseHash);
  const [importe, setImporte] = useState<Import | null>(lireImport);
  const importFini = useCallback(() => { if (window.location.hash.startsWith('#/importer/')) go('#/'); }, []);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastId, setLastId] = useState<string | null>(readLast);
  const [questionCount, setQuestionCount] = useState(0);
  const [retrying, setRetrying] = useState(false);
  // Analyse en cours suivie quel que soit l'écran affiché : titre de l'onglet et notification de fin.
  const [watchId, setWatchId] = useState<string | null>(readLast);

  useEffect(() => {
    const onHash = () => {
      setRoute(parseHash());
      const i = lireImport();
      if (i) setImporte(i); // DocAnalyser déjà ouvert : un nouvel envoi arrive dans le même onglet
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const routeId = 'id' in route ? route.id : null;

  // Chargement puis suivi (polling) de l'analyse affichée.
  useEffect(() => {
    if (!routeId) return;
    let stopped = false;
    let timer: number | undefined;
    setLoadError(null);

    const tick = async () => {
      try {
        const a = await analysisApi.getAnalysis(routeId);
        if (stopped) return;
        setAnalysis(a);
        setLastId(a.id);
        writeLast(a.id);
        if (a.status === 'running') {
          setWatchId(a.id);
          timer = window.setTimeout(tick, 1000);
        }
      } catch (e) {
        if (!stopped) setLoadError(e instanceof Error ? e.message : 'Analyse introuvable.');
      }
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [routeId]);

  const current = analysis && analysis.id === routeId ? analysis : null;

  useEffect(() => {
    setQuestionCount(current?.questions?.length ?? 0);
  }, [current?.id, current?.questions?.length]);

  useEffect(() => {
    if (!watchId) return;
    let stopped = false;
    let sawRunning = false;
    let timer: number | undefined;
    const tick = async () => {
      let a: Analysis;
      try {
        a = await analysisApi.getAnalysis(watchId);
      } catch {
        if (!stopped) setWatchId(null); // analyse supprimée entre-temps
        return;
      }
      if (stopped) return;
      if (a.status === 'running') {
        sawRunning = true;
        document.title = runningTitle(a);
        timer = window.setTimeout(tick, 3000);
        return;
      }
      if (!sawRunning) {
        setWatchId(null); // déjà terminée à l'ouverture de l'application : rien à signaler
        return;
      }
      // Terminée : le titre le signale jusqu'au retour sur la page, la notification si elle est autorisée.
      document.title = finishedTitle(a);
      const reset = () => {
        document.title = APP_TITLE;
        window.removeEventListener('focus', reset);
      };
      if (document.hasFocus()) window.setTimeout(reset, 5000);
      else window.addEventListener('focus', reset);
      notifyFinished(a, () => go(`#/analyse/${a.id}${a.status === 'done' ? '/synthese' : ''}`));
      setWatchId(null);
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [watchId]);

  const onLaunched = useCallback((a: Analysis) => {
    if (a.status === 'running') setWatchId(a.id);
    setAnalysis(a);
    setLastId(a.id);
    writeLast(a.id);
    go(`#/analyse/${a.id}`);
  }, []);

  const navigate = (view: View) => {
    if (view === 'new') go('#/');
    else if (view === 'history') go('#/historique');
    else if (view === 'settings') go('#/reglages');
    else if (lastId) go(`#/analyse/${lastId}${analysis?.id === lastId && analysis.status === 'done' ? '/synthese' : ''}`);
  };

  const cancel = async () => {
    if (!current) return;
    try {
      setAnalysis(await analysisApi.cancelAnalysis(current.id));
    } catch {
      /* l'analyse s'est peut-être terminée entre-temps */
    }
  };

  const retry = async () => {
    if (!current) return;
    setRetrying(true);
    try {
      onLaunched(await analysisApi.retryAnalysis(current.id));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Impossible de reprendre l’analyse.');
    } finally {
      setRetrying(false);
    }
  };

  const activeView: View =
    route.screen === 'config' ? 'new' : route.screen === 'history' ? 'history' : route.screen === 'settings' ? 'settings' : 'analysis';
  const nav = { active: activeView, onNavigate: navigate, analysisAvailable: !!lastId };

  const tabs = routeId
    ? {
        active: (route.screen === 'questions' ? 'questions' : route.screen === 'text' ? 'text' : 'report') as ReportTab,
        onChange: (tab: ReportTab) =>
          go(`#/analyse/${routeId}/${tab === 'questions' ? 'questions' : tab === 'text' ? 'texte' : 'synthese'}`),
        questions: questionCount,
      }
    : undefined;

  let body: React.ReactNode = null;
  if (route.screen === 'settings') {
    body = <SettingsScreen />;
  } else if (route.screen === 'history') {
    body = (
      <HistoryScreen
        onOpen={(it) => go(`#/analyse/${it.id}${it.status === 'done' ? '/synthese' : ''}`)}
        onNew={() => go('#/')}
        onDeleted={(id) => {
          if (id === lastId) {
            setLastId(null);
            writeLast(null);
          }
        }}
      />
    );
  } else if (route.screen !== 'config') {
    if (loadError) {
      body = (
        <main className="mx-auto flex max-w-[760px] flex-col items-center gap-4 px-6 py-20 text-center">
          <h1 className="m-0 text-[26px] font-bold">Analyse indisponible</h1>
          <p className="m-0 text-ink-muted">{loadError}</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => go('#/historique')}
              className="min-h-11 rounded-[10px] border border-line-strong bg-surface px-5 font-semibold text-ink"
            >
              Voir l’historique
            </button>
            <button
              type="button"
              onClick={() => go('#/')}
              className="min-h-11 rounded-[10px] border-none bg-primary px-5 font-semibold text-white hover:bg-primary-hover"
            >
              Nouvelle analyse
            </button>
          </div>
        </main>
      );
    } else if (!current) {
      body = <p className="py-20 text-center text-ink-muted">Chargement…</p>;
    } else if (route.screen === 'questions' && current.status === 'done' && current.result) {
      body = (
        <>
          <ReportBanner
            analysis={current}
            onNewAnalysis={() => go('#/')}
            chips={[current.mode_label, current.level_label, docCountLabel(current.documents.length), modelLabel(current)]}
            tabs={tabs}
          />
          <QuestionsPanel analysis={current} onCount={setQuestionCount} />
        </>
      );
    } else if (route.screen === 'text' && current.status === 'done' && current.result) {
      body = (
        <>
          <ReportBanner
            analysis={current}
            onNewAnalysis={() => go('#/')}
            chips={[current.mode_label, current.level_label, docCountLabel(current.documents.length), modelLabel(current)]}
            tabs={tabs}
          />
          <MarkdownEditor analysis={current} onSaved={setAnalysis} />
        </>
      );
    } else if (route.screen === 'result' && current.status === 'done' && current.result) {
      const props = { analysis: current, onNewAnalysis: () => go('#/'), tabs };
      body =
        current.result.kind === 'journey' ? (
          <JourneyReport {...props} result={current.result} />
        ) : (
          <ThemesReport {...props} result={current.result} onUpdate={setAnalysis} />
        );
    } else {
      body = (
        <ProgressScreen
          analysis={current}
          onCancel={cancel}
          onShowResult={() => go(`#/analyse/${current.id}/synthese`)}
          onBack={() => go('#/')}
          onRetry={current.status === 'failed' || current.status === 'cancelled' ? retry : undefined}
          retrying={retrying}
        />
      );
    }
  }

  const showingProgress =
    route.screen === 'progress' || ((route.screen === 'result' || route.screen === 'questions' || route.screen === 'text') &&
      current?.status !== 'done');

  return (
    <div className="min-h-screen bg-bg font-sans text-[15px] leading-normal text-ink">
      <AppHeader
        {...nav}
        right={showingProgress && current ? `${current.mode_label} · ${current.level_label} · ${modelLabel(current)}` : undefined}
        wide={route.screen === 'result' || route.screen === 'questions' || route.screen === 'text'}
      />

      {/* La configuration reste montée pour conserver documents et choix entre deux analyses. */}
      <div hidden={route.screen !== 'config'}>
        <ConfigScreen onLaunched={onLaunched} importe={importe} onImported={importFini} />
      </div>
      {body}
    </div>
  );
};
