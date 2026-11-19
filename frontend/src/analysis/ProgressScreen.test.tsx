import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProgressScreen } from './ProgressScreen';
import { Analysis } from './types';

afterEach(cleanup);

const base = {
  id: 'a1', status: 'running', progress: 40, steps: [], preview: [], mode: 'global', documents: [], result: null,
  error: null,
} as unknown as Analysis;

const noop = () => undefined;

describe('ProgressScreen', () => {
  it('demande confirmation avant d’annuler', () => {
    const onCancel = vi.fn();
    render(<ProgressScreen analysis={base} onCancel={onCancel} onShowResult={noop} onBack={noop} />);
    fireEvent.click(screen.getByRole('button', { name: 'Annuler l\'analyse' }));
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Continuer l’analyse' }));
    fireEvent.click(screen.getByRole('button', { name: 'Annuler l\'analyse' }));
    fireEvent.click(screen.getByRole('button', { name: 'Arrêter' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('renvoie vers les Réglages quand l’échec vient de la connexion', () => {
    const failed = { ...base, status: 'failed', error: 'La clé API a été refusée.', error_settings: true } as Analysis;
    render(<ProgressScreen analysis={failed} onCancel={noop} onShowResult={noop} onBack={noop} onRetry={noop} />);
    expect(screen.getByRole('link', { name: 'Ouvrir les Réglages' }).getAttribute('href')).toBe('#/reglages');
  });

  it('ne propose pas les Réglages pour un autre échec', () => {
    const failed = { ...base, status: 'failed', error: 'Réponse vide.' } as Analysis;
    render(<ProgressScreen analysis={failed} onCancel={noop} onShowResult={noop} onBack={noop} />);
    expect(screen.queryByRole('link', { name: 'Ouvrir les Réglages' })).toBeNull();
  });
});
