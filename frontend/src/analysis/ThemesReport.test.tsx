import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from './api';
import { ThemesReport } from './ThemesReport';
import { Analysis, Theme, ThemesResult } from './types';

vi.mock('./api', () => ({ analysisApi: { deepenTheme: vi.fn(), undoDeepen: vi.fn(), dismissDeepening: vi.fn(), getAnalysis: vi.fn() } }));
const api = vi.mocked(analysisApi);

afterEach(cleanup);

const theme = (title: string, extra: Partial<Theme> = {}): Theme => ({
  title, summary: `Résumé ${title}`, documents: ['a.txt'], points: [{ lead: `Point ${title}`, body: '', sources: [] }],
  quote: '', quote_check: '', quote_by: '', nuance: '', ...extra,
});

const make = (themes: Theme[], deepening: Analysis['deepening'] = null): Analysis => {
  const result: ThemesResult = {
    kind: 'themes', title: 'Étude', brief: 'Bref', themes, actions: [], sources: [{ document: 'a.txt', citations: 0 }],
    stats: { themes: themes.length, points: themes.length, quotes: 0, quotes_exact: 0, actions: 0 },
  };
  return {
    id: 'a1', status: 'done', progress: 100, steps: [], preview: [], title: 'Étude', mode: 'global', mode_label: 'Synthèse globale',
    level: 'synth', level_label: 'Synthétique', model_id: 'm', model_name: 'm', model_fallback: false, language: 'fr', cite: false,
    documents: [], created_at: '2026-11-19T10:00:00Z', result, markdown: '', error: null, deepening,
  } as Analysis;
};

describe('Approfondir ce thème', () => {
  it('lance l’approfondissement du thème choisi et transmet l’analyse mise à jour', async () => {
    const a = make([theme('Accueil'), theme('Tarifs')]);
    const running = make((a.result as ThemesResult).themes, { theme: 1, title: 'Tarifs', status: 'running', error: null });
    api.deepenTheme.mockResolvedValueOnce(running);
    const onUpdate = vi.fn();
    const { rerender } = render(<ThemesReport analysis={a} result={a.result as ThemesResult} onNewAnalysis={vi.fn()} onUpdate={onUpdate} />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Approfondir ce thème' })[1]);
    await waitFor(() => expect(api.deepenTheme).toHaveBeenCalledWith('a1', 1));
    expect(onUpdate).toHaveBeenCalledWith(running);

    rerender(<ThemesReport analysis={running} result={running.result as ThemesResult} onNewAnalysis={vi.fn()} onUpdate={onUpdate} />);
    expect(screen.getByRole('status').textContent).toContain('Approfondissement en cours');
    // Un seul à la fois : l'autre thème attend
    expect((screen.getByRole('button', { name: 'Approfondir ce thème' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('propose de revenir à la version précédente et affiche un échec', async () => {
    const deepened = theme('Accueil', { deepened: true, previous: theme('Accueil') });
    const a = make([deepened], { theme: 0, title: 'Accueil', status: 'failed', error: 'Réponse illisible.' });
    api.undoDeepen.mockResolvedValueOnce(make([theme('Accueil')]));
    render(<ThemesReport analysis={a} result={a.result as ThemesResult} onNewAnalysis={vi.fn()} onUpdate={vi.fn()} />);
    expect(screen.getByRole('alert').textContent).toContain('Réponse illisible.');
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Revenir à la version précédente' }));
    await waitFor(() => expect(api.undoDeepen).toHaveBeenCalledWith('a1', 0));
  });
});
