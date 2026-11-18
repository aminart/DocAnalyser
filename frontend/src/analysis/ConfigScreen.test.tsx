import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from './api';
import { ConfigScreen, countSelection } from './ConfigScreen';
import { Analysis, ModelInfo } from './types';

vi.mock('./api', () => ({
  MODELS_CHANGED: 'docanalyser:models-changed',
  analysisApi: {
    listModels: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    createAnalysis: vi.fn(),
  },
}));

const api = vi.mocked(analysisApi);

const model: ModelInfo = {
  id: 'CUSTOM_LLM:mistral-large',
  name: 'mistral-large',
  provider: 'CUSTOM_LLM',
  provider_label: 'Passerelle interne',
  description: '',
  quality: 5,
  speed: 2,
  economy: 2,
  tier: 'deep',
  configured: true,
};

afterEach(cleanup);

describe('ConfigScreen', () => {
  it('importe les documents, affiche l’erreur d’un fichier refusé et lance l’analyse avec les autres', async () => {
    api.listModels.mockResolvedValue([model]);
    api.uploadDocument.mockImplementation(async (file: File) => {
      if (file.name.endsWith('.doc')) {
        throw new Error('vieux.doc est à l’ancien format .doc : enregistrez-le au format .docx.');
      }
      return { id: 'd1', name: file.name, ext: 'docx', size_bytes: file.size, units: '3 paragraphes', pages: 1, warnings: [] };
    });
    api.createAnalysis.mockResolvedValue({ id: 'a1' } as Analysis);
    const onLaunched = vi.fn();
    const { container } = render(<ConfigScreen onLaunched={onLaunched} />);

    const launch = screen.getByRole('button', { name: /Analyser/ });
    expect((launch as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Importez au moins un document.')).toBeTruthy();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(['contenu'], 'notes.docx'), new File(['binaire'], 'vieux.doc')] },
    });

    const refused = (await screen.findByText(/ancien format \.doc/)).closest('li')!;
    expect(within(refused).getByText('Erreur')).toBeTruthy();
    const ok = screen.getByText('notes.docx').closest('li')!;
    expect(within(ok).getByText('Prêt')).toBeTruthy();

    await waitFor(() => expect((launch as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(launch);
    await waitFor(() => expect(onLaunched).toHaveBeenCalledWith({ id: 'a1' }));
    expect(api.createAnalysis).toHaveBeenCalledWith(
      expect.objectContaining({ document_ids: ['d1'], model_id: 'CUSTOM_LLM:mistral-large', mode: 'global' }),
    );
  });

  it('signale un serveur injoignable', async () => {
    api.listModels.mockRejectedValue(new Error('Serveur injoignable : l’application est-elle toujours lancée ?'));
    render(<ConfigScreen onLaunched={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toMatch(/Serveur injoignable/);
  });

  it('refuse une image glissée dans la zone sans l’envoyer au serveur', async () => {
    api.listModels.mockResolvedValue([model]);
    api.uploadDocument.mockClear();
    const { container } = render(<ConfigScreen onLaunched={vi.fn()} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['png'], 'capture.png')] } });

    const refused = (await screen.findByText(/Format \.png non lu/)).closest('li')!;
    expect(within(refused).getByText('Erreur')).toBeTruthy();
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it('analyse seulement les pages choisies d’un PDF', async () => {
    api.listModels.mockResolvedValue([model]);
    api.uploadDocument.mockResolvedValue({
      id: 'p1', name: 'rapport.pdf', ext: 'pdf', size_bytes: 10, units: '299 pages', pages: 299, warnings: [],
      sections: 'pages', last_section: 299,
    });
    api.createAnalysis.mockResolvedValue({ id: 'a2' } as Analysis);
    const { container } = render(<ConfigScreen onLaunched={vi.fn()} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['%PDF'], 'rapport.pdf')] } });

    const pages = await screen.findByLabelText('Pages à analyser dans rapport.pdf');
    fireEvent.change(pages, { target: { value: '12-45, 80' } });
    const launch = screen.getByRole('button', { name: /Analyser/ });
    await waitFor(() => expect((launch as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(launch);
    await waitFor(() =>
      expect(api.createAnalysis).toHaveBeenCalledWith(expect.objectContaining({ sections: { p1: '12-45, 80' } })),
    );
  });

  it('compte les pages d’une sélection', () => {
    expect(countSelection('12-45, 80', 299)).toBe(35);
    expect(countSelection('12 à 14 ; 290-', 299)).toBe(13);
    expect(countSelection('abc', 299)).toBeNull();
    expect(countSelection('', 299)).toBeNull();
  });
});
