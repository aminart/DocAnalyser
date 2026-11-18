import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from './api';
import { MarkdownEditor } from './MarkdownEditor';
import { formatRemaining } from './ProgressScreen';
import { Analysis } from './types';

vi.mock('./api', () => ({ analysisApi: { updateMarkdown: vi.fn() } }));
const api = vi.mocked(analysisApi);

afterEach(cleanup);

const base = { id: 'a1', markdown: '# Titre\n\nTexte.', markdown_edited: false } as Analysis;

describe('MarkdownEditor', () => {
  it('enregistre le texte modifié, puis revient au texte d’origine', async () => {
    const onSaved = vi.fn();
    api.updateMarkdown.mockResolvedValueOnce({ ...base, markdown: '# Titre corrigé', markdown_edited: true });
    const { rerender } = render(<MarkdownEditor analysis={base} onSaved={onSaved} />);
    const save = screen.getByRole('button', { name: 'Enregistrer' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText('Texte de la synthèse'), { target: { value: '# Titre corrigé' } });
    fireEvent.click(save);
    await waitFor(() => expect(api.updateMarkdown).toHaveBeenCalledWith('a1', '# Titre corrigé'));
    expect(await screen.findByText('Modifications enregistrées.')).toBeTruthy();

    const edited = onSaved.mock.calls[0][0] as Analysis;
    rerender(<MarkdownEditor analysis={edited} onSaved={onSaved} />);
    api.updateMarkdown.mockResolvedValueOnce(base);
    fireEvent.click(screen.getByRole('button', { name: 'Revenir au texte d’origine' }));
    await waitFor(() => expect(api.updateMarkdown).toHaveBeenLastCalledWith('a1', null));
  });
});

describe('formatRemaining', () => {
  it('écrit une durée lisible', () => {
    expect(formatRemaining(0)).toBe('presque terminé');
    expect(formatRemaining(30)).toBe('moins d’une minute');
    expect(formatRemaining(12 * 60)).toBe('≈ 12 min');
    expect(formatRemaining(160 * 60)).toBe('≈ 2 h 40');
    expect(formatRemaining(120 * 60)).toBe('≈ 2 h');
  });
});
