import React, { useState } from 'react';
import { FileUploadState } from '../hooks/useSynthesisJob';

interface DropzoneStepProps {
  filesState: FileUploadState[];
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (file: File) => void;
  onNext: () => void;
}

const SAMPLE_TEMPLATES = [
  {
    name: 'Rapport_Strategique_Q4_2026.md',
    label: 'Exemple : Rapport Stratégique & Financier',
    icon: 'analytics',
    content: `# Rapport Stratégique & Performance Financière 2026

## 1. Bilan Exécutif et Croissance
Le chiffre d'affaires consolidé atteint 48,6 M€ au quatrième trimestre, soit une croissance annuelle de 24% portée par l'adoption massive de notre plateforme SaaS Enterprise. La marge d'EBITDA progresse à 31% grâce à l'automatisation du pipeline d'ingestion documentaire.

## 2. Indicateurs Opérationnels & Satisfaction Client
Le taux de rétention net (NRR) s'établit à 118% sur le segment Grands Comptes. Le temps moyen de traitement des appels d'offres complexes (rapports PDF de 350 pages) a été réduit de 14 heures à 6 minutes par dossier.

## 3. Recommandations Stratégiques 2027
- Priorité Haute : Déployer l'infrastructure LLM hybride (Mistral Medium & Small) avec support des certificats PKI internes pour les banques et assurances.
- Priorité Haute : Généraliser le connecteur de classeurs Excel multi-feuilles pour les audits financiers.
- Priorité Moyenne : Étendre l'analyse automatique des réunions VTT/SRT à l'ensemble des équipes Customer Success.`,
  },
  {
    name: 'Comite_Produit_Transcription.vtt',
    label: 'Exemple : Transcription Réunion (.vtt)',
    icon: 'record_voice_over',
    content: `WEBVTT

00:01:10.000 --> 00:02:45.000
Claire (VP Product): Bonjour à tous. L'objectif de ce comité est de trancher l'architecture d'upload grand volume et la feuille de route Q1. Marc, où en sommes-nous sur les fichiers PDF de plus de 300 pages ?

00:02:46.000 --> 00:05:12.000
Marc (Principal Architect): Nous avons validé le découpage par chunks de 5 Mo côté navigateur et le parsing en streaming via PyMuPDF et OpenPyXL en mode read_only. Décision actée : nous utilisons mistral-medium-latest par défaut avec fallback sur mistral-small-latest pour les notes rapides.

00:05:15.000 --> 00:08:30.000
Sophie (Lead UX): Sur le parcours utilisateur, nos tests montrent un point de friction majeur lorsque l'utilisateur ne sait pas d'où vient un chiffre. Il faut absolument que chaque carte affiche un badge cliquable pointant vers la page ou la slide exacte. Marc prend l'action de livrer l'API d'ancrage d'ici vendredi prochain.

00:08:35.000 --> 00:11:00.000
Thomas (SecOps): Attention toutefois, une question reste en suspens concernant l'hébergement du certificat CA Bundle pour les clients bancaires on-premise : devons-nous supporter le rechargement à chaud sans redémarrer les workers Celery ?`,
  },
];

export const DropzoneStep: React.FC<DropzoneStepProps> = ({
  filesState,
  onAddFiles,
  onRemoveFile,
  onNext,
}) => {
  const [isDragging, setIsDragging] = useState(false);

  const allUploadsReady =
    filesState.length > 0 && filesState.every((item) => item.status === 'done');

  const handleLoadSample = (sample: (typeof SAMPLE_TEMPLATES)[number]) => {
    const blob = new Blob([sample.content], { type: 'text/plain;charset=utf-8' });
    const file = new File([blob], sample.name, { type: 'text/plain' });
    onAddFiles([file]);
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            onAddFiles(Array.from(e.dataTransfer.files));
          }
        }}
        className={`relative flex flex-col items-center justify-center rounded-3xl border-2 border-dashed p-12 text-center transition-all ${
          isDragging
            ? 'border-indigo-600 bg-indigo-50/60 scale-[1.01]'
            : 'border-slate-300 bg-white hover:border-indigo-400 hover:bg-slate-50/60'
        }`}
      >
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600 shadow-inner">
          <span className="material-symbols-outlined text-4xl">cloud_upload</span>
        </div>
        <h2 className="mt-4 text-xl font-bold text-slate-900">
          Importez vos documents bureautiques ou transcriptions
        </h2>
        <p className="mt-1.5 max-w-xl text-sm text-slate-500">
          Prise en charge native des fichiers volumineux (300+ pages PDF, classeurs Excel denses, présentations PowerPoint) par découpage asynchrone en chunks de 5 Mo.
        </p>

        <div className="mt-5 flex flex-wrap justify-center gap-2 text-xs font-medium text-slate-600">
          {['.PDF', '.DOCX / .DOC', '.PPTX / .PPT', '.XLSX / .CSV', '.VTT / .SRT', '.TXT / .MD'].map(
            (ext) => (
              <span
                key={ext}
                className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1"
              >
                {ext}
              </span>
            )
          )}
        </div>

        <label className="mt-6 inline-flex cursor-pointer items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700">
          <span className="material-symbols-outlined text-lg">upload_file</span>
          <span>Sélectionner un ou plusieurs fichiers</span>
          <input
            type="file"
            multiple
            className="hidden"
            accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.vtt,.srt,.txt,.md"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                onAddFiles(Array.from(e.target.files));
              }
            }}
          />
        </label>
      </div>

      {/* Boutons d'essai rapide avec documents pré-remplis */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <span className="material-symbols-outlined text-base text-indigo-600">science</span>
          Tester immédiatement avec un corpus d'exemple :
        </div>
        <div className="flex flex-wrap gap-2">
          {SAMPLE_TEMPLATES.map((sample) => (
            <button
              key={sample.name}
              type="button"
              onClick={() => handleLoadSample(sample)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50/60 px-3 py-1.5 text-xs font-semibold text-indigo-700 transition hover:bg-indigo-100"
            >
              <span className="material-symbols-outlined text-sm">{sample.icon}</span>
              {sample.label}
            </button>
          ))}
        </div>
      </div>

      {/* Liste des fichiers en cours d'upload ou prêts */}
      {filesState.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Lot documentaire prêt pour analyse ({filesState.length} fichier{filesState.length > 1 ? 's' : ''})
            </h3>
            <span className="text-xs text-slate-500">
              {filesState.length > 1 ? 'Synthèse croisée multi-fichiers activée' : 'Analyse mono-document'}
            </span>
          </div>

          <ul className="mt-4 divide-y divide-slate-100">
            {filesState.map((item, idx) => (
              <li key={`${item.file.name}-${idx}`} className="py-3.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                      <span className="material-symbols-outlined text-xl">
                        {item.status === 'done' ? 'check_circle' : 'description'}
                      </span>
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-slate-900">{item.file.name}</div>
                      <div className="text-xs text-slate-500">
                        {(item.file.size / 1024).toFixed(1)} Ko •{' '}
                        {item.status === 'done'
                          ? `Upload chunké terminé (${item.metadata?.total_chunks || 1} segment(s))`
                          : item.status === 'error'
                          ? item.error
                          : `Transfert en cours : ${item.progressPercent}%`}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onRemoveFile(item.file)}
                    className="rounded-lg p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                    title="Retirer ce fichier"
                  >
                    <span className="material-symbols-outlined text-lg">delete</span>
                  </button>
                </div>

                <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={`h-full transition-all duration-300 ${
                      item.status === 'error'
                        ? 'bg-rose-500'
                        : item.status === 'done'
                        ? 'bg-emerald-500'
                        : 'bg-indigo-600'
                    }`}
                    style={{ width: `${item.progressPercent}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-6 flex justify-end border-t border-slate-100 pt-4">
            <button
              type="button"
              disabled={!allUploadsReady}
              onClick={onNext}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              <span>Étape 2 : Choisir le mode d’analyse & le modèle LLM</span>
              <span className="material-symbols-outlined text-base">arrow_forward</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
