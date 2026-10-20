import React from 'react';
import { ModelOption, SynthesisMode } from '../types/synthesis';

interface ModeSelectorStepProps {
  selectedMode: SynthesisMode;
  onSelectMode: (mode: SynthesisMode) => void;
  availableModels: ModelOption[];
  selectedModel: string;
  onSelectModel: (modelId: string) => void;
  onBack: () => void;
  onLaunch: () => void;
  documentCount: number;
}

const MODES_META: {
  id: SynthesisMode;
  title: string;
  subtitle: string;
  icon: string;
  highlights: string[];
}[] = [
  {
    id: 'global_summary',
    title: 'Mode 1 — Synthèse Documentaire Globale',
    subtitle: 'Rapports stratégiques, études, PDF longs & classeurs financiers',
    icon: 'analytics',
    highlights: [
      'Résumé exécutif structuré',
      'Thématiques clés & arguments',
      'Chiffres & KPIs extraits',
      'Recommandations priorisées',
    ],
  },
  {
    id: 'transcript_summary',
    title: 'Mode 2 — Synthèse de Transcription',
    subtitle: 'Réunions, entretiens, fichiers VTT / SRT ou exports audio-to-text',
    icon: 'record_voice_over',
    highlights: [
      'Contexte, participants & agenda',
      'Clustering thématique',
      'Décisions actées (Decisions made)',
      'Plan d’action (Qui, Quoi, Quand) & Tensions',
    ],
  },
  {
    id: 'user_journey',
    title: 'Mode 3 — Extraction des Parcours Utilisateurs',
    subtitle: 'Ateliers UX, spécifications produit & processus métiers',
    icon: 'route',
    highlights: [
      'Personas & profils cibles',
      'Étapes chronologiques (Step-by-step)',
      'Objectifs, Pain points & Opportunités',
      'Diagramme de flux Mermaid interactif',
    ],
  },
  {
    id: 'raw_notes',
    title: 'Mode 4 — Synthèse de Notes en Vrac',
    subtitle: 'Brainstorming, notes de terrain & prises de notes disparates',
    icon: 'lightbulb',
    highlights: [
      'Dé-duplication et fusion des idées',
      'Catégorisation par piliers & tags',
      'Mise en forme propre et lisible',
      'Prochaines étapes suggérées',
    ],
  },
];

export const ModeSelectorStep: React.FC<ModeSelectorStepProps> = ({
  selectedMode,
  onSelectMode,
  availableModels,
  selectedModel,
  onSelectModel,
  onBack,
  onLaunch,
  documentCount,
}) => {
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <div>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-900">
              1. Choisissez le mode d'analyse adapté à votre intention métier
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Chaque mode active un prompt système spécialisé et un schéma de sortie structuré avec traçabilité granulaire.
            </p>
          </div>
          <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
            {documentCount} document(s) sélectionné(s)
          </span>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
          {MODES_META.map((m) => {
            const active = selectedMode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => onSelectMode(m.id)}
                className={`flex flex-col justify-between rounded-2xl border p-6 text-left transition-all ${
                  active
                    ? 'border-indigo-600 bg-indigo-50/40 ring-2 ring-indigo-600 shadow-sm'
                    : 'border-slate-200 bg-white hover:border-indigo-300 hover:shadow-sm'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between">
                    <div
                      className={`flex h-11 w-11 items-center justify-center rounded-xl ${
                        active ? 'bg-indigo-600 text-white' : 'bg-indigo-50 text-indigo-600'
                      }`}
                    >
                      <span className="material-symbols-outlined text-2xl">{m.icon}</span>
                    </div>
                    {active && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-indigo-600 px-2.5 py-0.5 text-xs font-semibold text-white">
                        <span className="material-symbols-outlined text-sm">check</span>
                        Sélectionné
                      </span>
                    )}
                  </div>
                  <h3 className="mt-4 text-base font-bold text-slate-900">{m.title}</h3>
                  <p className="mt-1 text-xs text-slate-500">{m.subtitle}</p>
                </div>

                <ul className="mt-4 space-y-1.5 border-t border-slate-100 pt-3">
                  {m.highlights.map((h) => (
                    <li key={h} className="flex items-center gap-2 text-xs text-slate-700">
                      <span className="material-symbols-outlined text-sm text-indigo-600">
                        check_small
                      </span>
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              </button>
            );
          })}
        </div>
      </div>

      {/* Sélecteur de Modèle LLM Multi-Fournisseurs (Google Gemini, Mistral AI, Custom .env) */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="material-symbols-outlined text-2xl text-indigo-600">memory</span>
            <div>
              <h3 className="font-bold text-slate-900">
                2. Choix du modèle LLM Multi-API (Configuré dans backend/.env)
              </h3>
              <p className="text-xs text-slate-500">
                Supporte simultanément Google Gemini API (1M tokens), Mistral AI et vos endpoints locaux avec CA Bundle.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {availableModels.map((model) => {
            const isSelected = selectedModel === model.id;
            const isGemini = model.provider === 'gemini';
            return (
              <label
                key={model.id}
                className={`flex cursor-pointer flex-col justify-between rounded-xl border p-4 transition ${
                  isSelected
                    ? 'border-indigo-600 bg-indigo-50/40 ring-1 ring-indigo-600'
                    : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <div>
                  <div className="mb-2 flex items-center justify-between gap-1">
                    <span
                      className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                        isGemini
                          ? 'bg-blue-100 text-blue-800'
                          : 'bg-amber-100 text-amber-800'
                      }`}
                    >
                      {model.provider_label || (isGemini ? 'Google Gemini' : 'Mistral AI')}
                    </span>
                    <input
                      type="radio"
                      name="llm_model"
                      value={model.id}
                      checked={isSelected}
                      onChange={() => onSelectModel(model.id)}
                      className="text-indigo-600 focus:ring-indigo-600"
                    />
                  </div>
                  <div className="text-sm font-bold text-slate-900">{model.label}</div>
                  <p className="mt-1 text-xs leading-relaxed text-slate-500">
                    {model.description}
                  </p>
                </div>
                <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2 text-[11px]">
                  <span className="font-semibold text-indigo-600">
                    Fenêtre : {(model.context_window / 1000).toFixed(0)}k tokens
                  </span>
                  <span
                    className={`font-medium ${
                      model.api_key_configured ? 'text-emerald-600' : 'text-slate-400'
                    }`}
                  >
                    {model.api_key_configured ? 'Clé API active' : 'Mode Démo (.env)'}
                  </span>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          <span className="material-symbols-outlined text-base">arrow_back</span>
          Retour aux documents
        </button>

        <button
          type="button"
          onClick={onLaunch}
          className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700"
        >
          <span className="material-symbols-outlined text-base">auto_awesome</span>
          Lancer la génération de la synthèse
        </button>
      </div>
    </div>
  );
};
