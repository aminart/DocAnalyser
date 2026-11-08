import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from './api';
import { Answer, QuestionsPanel, suggestionsFor } from './QuestionsPanel';
import { Analysis, Question } from './types';

vi.mock('./api', () => ({
  analysisApi: {
    listQuestions: vi.fn(),
    askQuestion: vi.fn(),
    clearQuestions: vi.fn(),
    getSource: vi.fn(() => new Promise(() => undefined)),
    exportUrl: vi.fn(() => '#'),
  },
}));

const api = vi.mocked(analysisApi);

const analysis = {
  id: 'a1',
  mode: 'global',
  documents: [{ id: 'd1', name: 'entretiens.docx', ext: 'docx', size_bytes: 1, units: '', pages: 1, warnings: [] }],
  result: { kind: 'themes', themes: [{ title: 'Onboarding' }, { title: 'Tarifs' }] },
  questions: [],
} as unknown as Analysis;

const question = (over: Partial<Question>): Question => ({
  id: 'q1',
  question: 'Que disent-ils des tarifs ?',
  answer: '',
  status: 'running',
  error: null,
  sources: [],
  scope: '',
  passages: 0,
  keywords: [],
  model_name: 'mistral-large',
  created_at: '2026-11-07T00:00:00Z',
  ...over,
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(cleanup);

describe('Answer', () => {
  it('rend les citations en sources cliquables, une source introuvable étant signalée', () => {
    const onSource = vi.fn();
    render(
      <Answer
        text={'Les tarifs sont jugés **trop élevés** [[entretiens.docx | §4]].\n- Repère faux [[entretiens.docx | §99]]'}
        sources={[
          { document: 'entretiens.docx', location: '§4', found: true },
          { document: 'entretiens.docx', location: '§99', found: false },
        ]}
        onSource={onSource}
      />,
    );
    expect(screen.getByText('trop élevés').tagName).toBe('STRONG');
    fireEvent.click(screen.getByRole('button', { name: /entretiens §4/ }));
    expect(onSource).toHaveBeenCalledWith({
      document: 'entretiens.docx',
      location: '§4',
      text: 'Les tarifs sont jugés trop élevés .',
    });
    expect(screen.getByRole('button', { name: /entretiens §99/ }).getAttribute('title')).toMatch(/introuvable/);
    expect(screen.getByRole('listitem').textContent).toContain('Repère faux');
  });
});

describe('suggestionsFor', () => {
  it('propose une question par thème de la synthèse', () => {
    expect(suggestionsFor(analysis)).toEqual([
      'Que disent les documents sur « Onboarding » ?',
      'Que disent les documents sur « Tarifs » ?',
      'Sur quels points les documents divergent-ils ?',
    ]);
  });
});

describe('QuestionsPanel', () => {
  it('envoie la question, suit la réponse en cours et affiche ses sources', async () => {
    const done = question({
      status: 'done',
      answer: 'Ils les trouvent trop élevés [[entretiens.docx | §4]].',
      sources: [{ document: 'entretiens.docx', location: '§4', found: true }],
      scope: 'search',
      passages: 3,
      keywords: ['prix', 'coût'],
    });
    api.listQuestions.mockResolvedValueOnce([]).mockResolvedValue([done]);
    api.askQuestion.mockResolvedValue(question({}));
    const onCount = vi.fn();
    render(<QuestionsPanel analysis={analysis} onCount={onCount} />);

    fireEvent.change(screen.getByLabelText('Votre question'), { target: { value: 'Que disent-ils des tarifs ?' } });
    fireEvent.keyDown(screen.getByLabelText('Votre question'), { key: 'Enter' });

    await waitFor(() => expect(api.askQuestion).toHaveBeenCalledWith('a1', 'Que disent-ils des tarifs ?'));
    expect(await screen.findByText('Recherche dans les documents…')).toBeTruthy();
    expect(await screen.findByText(/Ils les trouvent trop élevés/, {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByRole('button', { name: /entretiens §4/ })).toBeTruthy();
    expect(screen.getByText(/3 passages retrouvés par la recherche \(mots-clés : prix, coût\)/)).toBeTruthy();
    expect(onCount).toHaveBeenLastCalledWith(1);
  });

  it('affiche l’erreur renvoyée par le serveur', async () => {
    api.listQuestions.mockResolvedValue([]);
    api.askQuestion.mockRejectedValue(new Error('Une réponse est déjà en cours de rédaction.'));
    render(<QuestionsPanel analysis={analysis} />);
    fireEvent.click(screen.getByRole('button', { name: 'Que disent les documents sur « Tarifs » ?' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Une réponse est déjà en cours de rédaction.');
  });
});
