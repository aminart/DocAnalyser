import React, { useCallback, useEffect, useState } from 'react';
import { analysisApi } from '../analysis/api';
import { ConfigScreen } from '../analysis/ConfigScreen';
import { JourneyReport } from '../analysis/JourneyReport';
import { ProgressScreen } from '../analysis/ProgressScreen';
import { ThemesReport } from '../analysis/ThemesReport';
import { Analysis } from '../analysis/types';
import { AppHeader, View, modelLabel } from '../analysis/ui';

type Route = { screen: 'config' } | { screen: 'progress' | 'result'; id: string };

const LAST_ANALYSIS_KEY = 'analyse-documentaire:last';

const parseHash = (): Route => {
  const m = window.location.hash.match(/^#\/analyse\/([\w-]+)(\/synthese)?$/);
  return m ? { screen: m[2] ? 'result' : 'progress', id: m[1] } : { screen: 'config' };
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

const writeLast = (id: string) => {
  try {
    localStorage.setItem(LAST_ANALYSIS_KEY, id);
  } catch {
    /* stockage indisponible */
  }
};

export const App: React.FC = () => {
  const [route, setRoute] = useState<Route>(parseHash);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastId, setLastId] = useState<string | null>(readLast);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const routeId = route.screen === 'config' ? null : route.id;

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
        if (a.status === 'running') timer = window.setTimeout(tick, 1000);
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

  const onLaunched = useCallback((a: Analysis) => {
    setAnalysis(a);
    setLastId(a.id);
    writeLast(a.id);
    go(`#/analyse/${a.id}`);
  }, []);

  const navigate = (view: View) => {
    if (view === 'new') go('#/');
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

  const activeView: View = route.screen === 'config' ? 'new' : 'analysis';
  const nav = { active: activeView, onNavigate: navigate, analysisAvailable: !!lastId };

  let body: React.ReactNode = null;
  if (route.screen !== 'config') {
    if (loadError) {
      body = (
        <main className="mx-auto flex max-w-[760px] flex-col items-center gap-4 px-6 py-20 text-center">
          <h1 className="m-0 text-[26px] font-bold">Analyse indisponible</h1>
          <p className="m-0 text-muted">{loadError}</p>
          <button
            type="button"
            onClick={() => go('#/')}
            className="min-h-11 rounded-[10px] border-none bg-ink px-5 font-semibold text-white"
          >
            Nouvelle analyse
          </button>
        </main>
      );
    } else if (!current) {
      body = <p className="py-20 text-center text-muted">Chargement…</p>;
    } else if (route.screen === 'result' && current.status === 'done' && current.result) {
      const props = { analysis: current, onNewAnalysis: () => go('#/') };
      body =
        current.result.kind === 'journey' ? (
          <JourneyReport {...props} result={current.result} />
        ) : (
          <ThemesReport {...props} result={current.result} />
        );
    } else {
      body = (
        <ProgressScreen
          analysis={current}
          onCancel={cancel}
          onShowResult={() => go(`#/analyse/${current.id}/synthese`)}
          onBack={() => go('#/')}
        />
      );
    }
  }

  const showingProgress = route.screen === 'progress' || (route.screen === 'result' && current?.status !== 'done');

  return (
    <div className="min-h-screen bg-page font-sans text-[15px] leading-normal text-ink">
      {showingProgress && current ? (
        <AppHeader right={`${current.mode_label} · ${current.level_label} · ${modelLabel(current)}`} />
      ) : (
        <AppHeader {...nav} wide={route.screen === 'result'} />
      )}

      {/* La configuration reste montée pour conserver documents et choix entre deux analyses. */}
      <div hidden={route.screen !== 'config'}>
        <ConfigScreen onLaunched={onLaunched} />
      </div>
      {body}
    </div>
  );
};
