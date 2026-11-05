import React, { useEffect, useRef, useState } from 'react';
import { connectionsApi, MODELS_CHANGED } from './api';
import { Connection, ConnectionForm, ConnectionsState, ConnectionTest } from './types';

/**
 * Réglages : connexions aux modèles. Même logique et même fenêtre que les écrans de SpecGen et d'Audit
 * ergonomique (clé chiffrée, certificat importé, test avec diagnostic, .env prioritaire), avec plusieurs
 * connexions et, pour chacune, plusieurs modèles.
 */

const EXPIRY_WARNING_DAYS = 30;

const date = (iso: string) => new Date(iso).toLocaleDateString('fr-FR');
const dateTime = (iso: string) => new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });

const expiry = (expiresAt?: string): { label: string; tone: 'muted' | 'warning' | 'error' } | null => {
  if (!expiresAt) return null;
  const days = (new Date(expiresAt).getTime() - Date.now()) / 86_400_000;
  if (days < 0) return { label: `expiré depuis le ${date(expiresAt)}`, tone: 'error' };
  if (days < EXPIRY_WARNING_DAYS) return { label: `expire bientôt, le ${date(expiresAt)}`, tone: 'warning' };
  return { label: `expire le ${date(expiresAt)}`, tone: 'muted' };
};

const toBase64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

/* ---------- Petits éléments ---------- */

const Svg: React.FC<{ d: React.ReactNode; size?: number; className?: string }> = ({ d, size = 18, className }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
    {d}
  </svg>
);
const I = {
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>,
  eyeOff: <><path d="M10.6 5.1A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.8 9.8 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /><path d="m2 2 20 20" /></>,
  shield: <><path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-4" /></>,
  shieldAlert: <><path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6l-8-3Z" /><path d="M12 8v4M12 15.5v.5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  check: <path d="m5 12 5 5 9-10" />,
  alert: <><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17v.5" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
  close: <path d="M6 6l12 12M18 6 6 18" />,
};

const Field: React.FC<{ label: string; htmlFor?: string; optional?: boolean; hint?: React.ReactNode; children: React.ReactNode }> = ({
  label, htmlFor, optional, hint, children,
}) => (
  <div className="flex flex-col gap-2">
    {React.createElement(htmlFor ? 'label' : 'span', { htmlFor, className: 'text-[15px] font-medium' }, label,
      optional ? <span className="font-normal text-ink-subtle"> (facultatif)</span> : null)}
    {children}
    {hint && <p className="m-0 text-[13px] text-ink-subtle">{hint}</p>}
  </div>
);

const inputClass = (invalid?: boolean) =>
  `min-h-[44px] w-full min-w-0 rounded-lg border bg-surface px-3.5 text-[15px] text-ink placeholder:text-ink-subtle focus:outline-none focus:ring-[3px] focus:ring-accent-soft ${
    invalid ? 'border-[1.5px] border-danger focus:border-danger' : 'border-line-strong focus:border-accent'
  }`;

const smallButton = 'min-h-[36px] rounded-md border border-line-strong bg-surface px-3 text-[13px] font-medium text-ink hover:bg-surface-3';

const TestBanner: React.FC<{ test: ConnectionTest }> = ({ test }) =>
  test.ok ? (
    <div role="status" className="flex items-center gap-3 rounded-lg border border-success-soft bg-success-soft px-4 py-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-success text-surface">
        <Svg d={I.check} size={14} />
      </span>
      <div>
        <p className="m-0 text-[15px] font-medium text-success-text">{test.title}</p>
        <p className="m-0 mt-0.5 text-[13px] text-success-text">
          Testée le {dateTime(test.at)} · {test.message}
        </p>
      </div>
    </div>
  ) : (
    <div role="alert" className="flex gap-3 rounded-lg border border-danger-soft bg-danger-soft p-4">
      <Svg d={I.alert} size={20} className="mt-0.5 shrink-0 text-danger-text" />
      <div>
        <p className="m-0 text-[15px] font-medium text-danger-text">{test.title}</p>
        <p className="m-0 mt-1 text-sm leading-normal text-ink-body">{test.message}</p>
      </div>
    </div>
  );

/* ---------- Formulaire d'une connexion ---------- */

const emptyForm = (): ConnectionForm => ({ kind: 'openai', name: '', api_base: '', api_key: '', models: [], context_tokens: null });

const ConnectionEditor: React.FC<{
  existing: Connection | null;
  onSaved: (state: ConnectionsState) => void;
  onCancel: () => void;
}> = ({ existing, onSaved, onCancel }) => {
  const [form, setForm] = useState<ConnectionForm>(() =>
    existing
      ? { kind: 'openai', name: existing.name, api_base: existing.api_base, api_key: existing.has_api_key ? null : '',
          models: existing.models, context_tokens: existing.context_tokens }
      : emptyForm(),
  );
  const [showKey, setShowKey] = useState(false);
  const [newModel, setNewModel] = useState('');
  const [pendingCert, setPendingCert] = useState<File | null>(null);
  const [dropCert, setDropCert] = useState(false);
  const [test, setTest] = useState<ConnectionTest | null>(existing?.last_test ?? null);
  const [busy, setBusy] = useState<'test' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const certInput = useRef<HTMLInputElement>(null);

  const set = <K extends keyof ConnectionForm>(key: K, value: ConnectionForm[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    // Le dernier test ne vaut plus si l'adresse ou la clé change (le certificat et le type sont traités à part).
    if (key === 'api_base' || key === 'api_key') setTest(null);
  };
  const complete = /^https?:\/\//i.test(form.api_base.trim()) && form.models.length + (newModel.trim() ? 1 : 0) > 0;
  const failed = test && !test.ok ? test.field : null;
  const certificate = dropCert ? null : existing?.certificate ?? null;
  const exp = expiry(certificate?.expires_at);

  const addModels = (raw: string) => {
    const names = raw.split(/[,\n]/).map((m) => m.trim()).filter(Boolean);
    if (names.length) setForm((f) => ({ ...f, models: [...f.models, ...names.filter((n) => !f.models.includes(n))] }));
  };
  const withPendingModel = (): ConnectionForm => {
    const extra = newModel.split(/[,\n]/).map((m) => m.trim()).filter((m) => m && !form.models.includes(m));
    return extra.length ? { ...form, models: [...form.models, ...extra] } : form;
  };

  const run = async (kind: 'test' | 'save', action: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const doTest = () =>
    run('test', async () => {
      const f = withPendingModel();
      setForm(f);
      setNewModel('');
      setTest(
        await connectionsApi.test({
          ...f,
          id: existing?.id,
          certificate_b64: pendingCert ? await toBase64(pendingCert) : undefined,
        }),
      );
    });

  const doSave = () =>
    run('save', async () => {
      const f = withPendingModel();
      const payload = { ...f, last_test: test ?? undefined };
      let state = existing ? await connectionsApi.update(existing.id, payload) : await connectionsApi.create(payload);
      const id = existing?.id ?? state.created;
      if (id && dropCert && existing?.certificate) state = await connectionsApi.removeCertificate(id);
      if (id && pendingCert) {
        await connectionsApi.uploadCertificate(id, pendingCert);
        // L'import efface le dernier test : celui fait avec ce certificat avant d'enregistrer reste valable.
        state = test ? await connectionsApi.update(id, { ...f, api_key: null, last_test: test }) : await connectionsApi.list();
      }
      window.dispatchEvent(new Event(MODELS_CHANGED));
      onSaved(state);
    });

  const suggestions = (test?.available ?? []).filter((m) => !form.models.includes(m) && !form.models.includes(m.split(':')[0]));

  return (
    <section className="rounded-xl border border-line bg-surface" aria-label={existing ? `Modifier ${existing.name}` : 'Nouvelle connexion'}>
      <div className="px-6 pb-2 pt-6 sm:px-8">
        <h2 className="m-0 text-xl font-bold text-accent">{existing ? `Modifier « ${existing.name} »` : 'Nouvelle connexion'}</h2>
        <p className="m-0 mt-1.5 text-sm text-ink-muted">Ces informations sont fournies par votre service informatique ou par le fournisseur. Elles restent sur ce poste.</p>
      </div>

      <div className="flex flex-col gap-6 px-6 pb-6 pt-4 sm:px-8">
        {test && <TestBanner test={test} />}

        <Field label="Nom" htmlFor="c-name" hint="Affiché à côté de chaque modèle, au moment de choisir le modèle d'une analyse.">
          <input id="c-name" className={inputClass()} value={form.name} onChange={(e) => set('name', e.target.value)}
            placeholder="Passerelle interne" />
        </Field>

        <Field label="URL du service" htmlFor="c-url" hint="Exemples : https://passerelle.mon-entreprise.fr/v1 · Ollama : http://localhost:11434/v1">
          <input id="c-url" type="url" className={inputClass(failed === 'api_base')} value={form.api_base}
            onChange={(e) => set('api_base', e.target.value)} placeholder="https://llm.mon-entreprise.fr/v1" />
        </Field>

        {form.api_key === null ? (
          <Field label="Clé API" hint="Chiffrée avec votre compte Windows : elle n'est jamais réaffichée en clair.">
            <div className={`flex min-h-[48px] items-center gap-3 rounded-lg border bg-surface-2 pl-3.5 pr-2 ${failed === 'api_key' ? 'border-[1.5px] border-danger' : 'border-line-strong'}`}>
              <Svg d={I.lock} className="text-ink-muted" />
              <span className="flex-1 text-[15px] tracking-[0.08em] text-ink-body">•••• •••• •••• {existing?.api_key_hint}</span>
              <button type="button" className={smallButton} onClick={() => set('api_key', '')}>Modifier</button>
            </div>
          </Field>
        ) : (
          <Field label="Clé API" htmlFor="c-key" optional
            hint="Laissez vide pour un serveur qui n'en demande pas (Ollama, LM Studio sur ce poste).">
            <div className="flex gap-2">
              <input id="c-key" type={showKey ? 'text' : 'password'} className={inputClass(failed === 'api_key')} value={form.api_key}
                onChange={(e) => set('api_key', e.target.value)} placeholder="Collez votre clé API" autoComplete="off" />
              <button type="button" onClick={() => setShowKey((v) => !v)} aria-label={showKey ? 'Masquer la clé' : 'Afficher la clé'}
                className="flex min-h-[44px] w-11 shrink-0 items-center justify-center rounded-lg border border-line-strong bg-surface text-ink-muted hover:bg-surface-3">
                <Svg d={showKey ? I.eyeOff : I.eye} />
              </button>
            </div>
            {existing?.has_api_key && (
              <button type="button" className="self-start border-none bg-transparent p-0 text-[13px] font-medium text-accent underline" onClick={() => set('api_key', null)}>
                Garder la clé enregistrée
              </button>
            )}
          </Field>
        )}

        <Field label="Certificat de l'entreprise" optional={!certificate && !pendingCert}
          hint={certificate || pendingCert ? undefined : 'Seulement pour une adresse https dont le certificat est signé par une autorité interne. Le fichier est copié dans l\'application.'}>
          {certificate || pendingCert ? (
            <div className={`flex items-center gap-3 rounded-lg bg-surface px-3.5 py-3 ${failed === 'certificate' ? 'border-[1.5px] border-danger' : 'border border-line-strong'}`}>
              <Svg d={failed === 'certificate' || exp?.tone === 'error' ? I.shieldAlert : I.shield} size={22}
                className={`shrink-0 ${failed === 'certificate' || exp?.tone === 'error' ? 'text-danger-text' : 'text-accent'}`} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{pendingCert?.name ?? certificate?.name}</div>
                <div className={`text-xs ${failed === 'certificate' || exp?.tone === 'error' ? 'text-danger-text' : exp?.tone === 'warning' ? 'text-warning-text' : 'text-ink-muted'}`}>
                  {failed === 'certificate'
                    ? 'Non reconnu par le serveur'
                    : pendingCert
                      ? 'Sera enregistré avec la connexion'
                      : [certificate?.imported_at && `Importé le ${date(certificate.imported_at)}`, exp?.label].filter(Boolean).join(' · ')}
                </div>
              </div>
              <button type="button" className={smallButton} onClick={() => certInput.current?.click()}>Remplacer</button>
              <button type="button" className={smallButton} aria-label="Retirer le certificat"
                onClick={() => { setPendingCert(null); setDropCert(true); setTest(null); }}>
                Retirer
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => certInput.current?.click()}
              className={`flex min-h-[52px] items-center justify-center gap-2 rounded-lg border-[1.5px] border-dashed bg-transparent text-sm font-medium text-accent hover:border-accent hover:bg-accent-softer ${failed === 'certificate' ? 'border-danger' : 'border-line-dashed'}`}>
              <Svg d={I.plus} /> Choisir le fichier .crt
            </button>
          )}
          <input ref={certInput} type="file" accept=".crt,.pem,.cer" className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) { setPendingCert(file); setDropCert(false); setTest(null); }
              e.target.value = '';
            }} />
        </Field>

        <Field label="Modèles" hint="Chaque modèle sera proposé au moment de lancer une analyse. Le profil (approfondi, équilibré, rapide) est déduit de son nom.">
          <div className={`flex flex-wrap items-center gap-2 rounded-lg border bg-surface px-2.5 py-2 ${failed === 'models' ? 'border-[1.5px] border-danger' : 'border-line-strong'}`}>
            {form.models.map((m) => {
              const missing = test?.missing?.includes(m);
              return (
                <span key={m} className={`inline-flex items-center gap-1 rounded-md py-1 pl-2.5 pr-1 text-[13px] font-medium ${missing ? 'bg-warning-soft text-warning-text' : 'bg-accent-soft text-accent-ink'}`}
                  title={missing ? 'Introuvable sur le serveur lors du dernier test' : undefined}>
                  {m}
                  <button type="button" aria-label={`Retirer ${m}`} onClick={() => set('models', form.models.filter((x) => x !== m))}
                    className="flex h-5 w-5 items-center justify-center rounded border-none bg-transparent text-current hover:bg-surface-3">
                    <Svg d={I.close} size={12} />
                  </button>
                </span>
              );
            })}
            <input aria-label="Ajouter un modèle" className="min-h-[32px] min-w-[180px] flex-1 border-none bg-transparent px-1 text-[15px] text-ink placeholder:text-ink-subtle focus:outline-none"
              value={newModel} placeholder={form.models.length ? 'Ajouter un modèle…' : 'Nom du modèle, puis Entrée (ex. mistral-large-latest)'}
              onChange={(e) => setNewModel(e.target.value)}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ',') && newModel.trim()) {
                  e.preventDefault();
                  addModels(newModel);
                  setNewModel('');
                }
              }}
              onBlur={() => { if (newModel.trim()) { addModels(newModel); setNewModel(''); } }} />
          </div>
          {suggestions.length > 0 && (
            <div className="flex flex-col gap-2 rounded-lg bg-surface-2 px-3.5 py-3">
              <span className="text-[13px] font-medium text-ink-muted">Proposés par le serveur : cliquez pour ajouter</span>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((m) => (
                  <button key={m} type="button" onClick={() => addModels(m)}
                    className="inline-flex items-center gap-1 rounded-md border border-line-strong bg-surface px-2.5 py-1 text-[13px] text-ink hover:border-accent hover:text-accent">
                    <Svg d={I.plus} size={12} /> {m}
                  </button>
                ))}
              </div>
            </div>
          )}
        </Field>

        <details className="border-t border-line pt-4">
          <summary className="cursor-pointer text-sm font-medium text-ink-muted hover:text-ink">
            Options avancées · fenêtre de contexte {form.context_tokens ? `${form.context_tokens.toLocaleString('fr-FR')} tokens` : 'par défaut'}
          </summary>
          <div className="mt-4 max-w-[320px]">
            <Field label="Fenêtre de contexte (tokens)" htmlFor="c-ctx" hint="Taille des documents que le modèle accepte en une requête : au-delà, l'analyse découpe le corpus.">
              <input id="c-ctx" type="number" min={1000} className={inputClass()} value={form.context_tokens ?? ''}
                placeholder="128 000"
                onChange={(e) => set('context_tokens', e.target.value ? Number(e.target.value) : null)} />
            </Field>
          </div>
        </details>

        {error && (
          <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger-text">{error}</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-b-xl border-t border-line bg-surface-2 px-6 py-4 sm:px-8">
        <p className="m-0 flex-[1_1_200px] text-[13px] text-ink-subtle">
          {!complete
            ? "Renseignez l'URL et au moins un modèle pour tester la connexion."
            : test && !test.ok ? "Vous pouvez enregistrer malgré l'échec, l'analyse risque de ne pas fonctionner." : "Testez la connexion avant d'enregistrer."}
        </p>
        <button type="button" onClick={onCancel} className="min-h-[44px] rounded-lg border-none bg-transparent px-3 text-sm font-medium text-ink-muted hover:text-ink">
          Annuler
        </button>
        <button type="button" disabled={!complete || busy !== null} onClick={doTest}
          className="min-h-[44px] rounded-lg border border-line-strong bg-surface px-4 text-sm font-medium text-ink hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50">
          {busy === 'test' ? 'Test en cours (jusqu’à 30 s)…' : test && !test.ok ? 'Tester à nouveau' : 'Tester la connexion'}
        </button>
        <button type="button" disabled={!complete || busy !== null} onClick={doSave}
          className="min-h-[44px] rounded-lg border-none bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-primary-disabled disabled:text-primary-on-disabled">
          {busy === 'save' ? 'Enregistrement…' : 'Enregistrer'}
        </button>
      </div>
    </section>
  );
};

/* ---------- Une connexion, en lecture ---------- */

const ConnectionCard: React.FC<{
  c: Connection;
  onEdit: () => void;
  onDelete: () => void;
  onTested: (test: ConnectionTest) => void;
}> = ({ c, onEdit, onDelete, onTested }) => {
  const [busy, setBusy] = useState(false);
  const fromEnv = c.source === 'env';
  const exp = expiry(c.certificate?.expires_at);
  const test = c.last_test;

  const runTest = async () => {
    setBusy(true);
    try {
      onTested(await connectionsApi.test({ id: c.id, kind: c.kind, name: c.name, api_base: c.api_base, api_key: null, models: c.models, context_tokens: c.context_tokens }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="flex flex-col gap-4 rounded-xl border border-line bg-surface px-6 py-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="m-0 text-[17px] font-bold">{c.name}</h3>
            {fromEnv && <span className="rounded-md bg-warning-soft px-2 py-0.5 text-xs font-semibold text-warning-text">Fichier .env · {c.env_prefix}</span>}
          </div>
          <p className="m-0 mt-1 break-all text-[13px] text-ink-muted">{c.api_base}</p>
        </div>
        {!fromEnv && (
          <div className="flex flex-wrap gap-2">
            <button type="button" className={smallButton} disabled={busy} onClick={runTest}>{busy ? 'Test…' : 'Tester'}</button>
            <button type="button" className={smallButton} onClick={onEdit}>Modifier</button>
            <button type="button" className={`${smallButton} text-danger-text`} onClick={onDelete}>Supprimer</button>
          </div>
        )}
      </div>

      <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-[150px_1fr]">
        <dt className="text-ink-muted">Clé API</dt>
        <dd className="m-0 flex items-center gap-1.5">
          {c.has_api_key ? <><Svg d={I.lock} size={14} className="text-ink-muted" /> •••• {c.api_key_hint || 'enregistrée'}</> : <span className="text-ink-subtle">aucune</span>}
        </dd>
        {c.kind === 'openai' && (
          <>
            <dt className="text-ink-muted">Certificat</dt>
            <dd className={`m-0 ${exp?.tone === 'error' ? 'text-danger-text' : exp?.tone === 'warning' ? 'text-warning-text' : ''}`}>
              {c.certificate ? [c.certificate.name, exp?.label].filter(Boolean).join(' · ') : <span className="text-ink-subtle">aucun</span>}
            </dd>
          </>
        )}
        <dt className="text-ink-muted">Modèles</dt>
        <dd className="m-0 flex flex-wrap gap-1.5">
          {c.models.length ? c.models.map((m) => (
            <span key={m} className={`rounded-md px-2 py-0.5 font-medium ${test?.missing?.includes(m) ? 'bg-warning-soft text-warning-text' : 'bg-accent-soft text-accent-ink'}`}>{m}</span>
          )) : <span className="text-warning-text">aucun : ajoutez au moins un modèle</span>}
        </dd>
      </dl>

      {fromEnv ? (
        <p className="m-0 text-[13px] text-ink-subtle">Déclarée dans le fichier .env : modifiable seulement dans ce fichier, prioritaire sur cet écran.</p>
      ) : test ? (
        <p className={`m-0 flex items-center gap-1.5 text-[13px] ${test.ok ? 'text-success-text' : 'text-danger-text'}`}>
          <Svg d={test.ok ? I.check : I.alert} size={14} />
          {test.title} · {test.ok ? test.message : test.message.split('. ')[0]} · {dateTime(test.at)}
        </p>
      ) : (
        <p className="m-0 text-[13px] text-ink-subtle">Pas encore testée.</p>
      )}
    </article>
  );
};

/* ---------- Écran ---------- */

export const SettingsScreen: React.FC = () => {
  const [state, setState] = useState<ConnectionsState | null>(null);
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    connectionsApi.list().then(setState).catch((e: Error) => setError(e.message));
  }, []);

  if (!state) {
    return <main className="mx-auto max-w-[920px] px-6 py-12 text-ink-muted">{error ?? 'Chargement des réglages…'}</main>;
  }

  const saved = (s: ConnectionsState) => {
    setState(s);
    setEditing(null);
    setNotice('Connexion enregistrée : ses modèles sont proposés dans « Nouvelle analyse ».');
  };
  const remove = async (c: Connection) => {
    if (!window.confirm(`Supprimer la connexion « ${c.name} », sa clé et son certificat de ce poste ?`)) return;
    try {
      setState(await connectionsApi.remove(c.id));
      window.dispatchEvent(new Event(MODELS_CHANGED));
      setNotice(`Connexion « ${c.name} » supprimée.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const tested = (id: string, test: ConnectionTest) =>
    setState((s) => s && { ...s, connections: s.connections.map((c) => (c.id === id ? { ...c, last_test: test } : c)) });

  const editingConnection = editing && editing !== 'new' ? state.connections.find((c) => c.id === editing) ?? null : null;
  const hasEnv = state.connections.some((c) => c.source === 'env');

  return (
    <main className="mx-auto flex w-full max-w-[920px] flex-col gap-6 px-6 pb-16 pt-11">
      <header>
        <h1 className="m-0 text-[34px] font-bold leading-[1.15] tracking-[-0.02em]">Réglages</h1>
        <p className="m-0 mt-2 text-ink-muted">
          Connexions aux modèles de langage : la passerelle compatible OpenAI de votre organisation, ou un modèle sur ce poste (Ollama, LM Studio). Chaque connexion peut proposer plusieurs modèles.
        </p>
      </header>

      {hasEnv && (
        <div className="flex gap-3 rounded-[10px] border border-line bg-surface px-5 py-4 text-[13px] leading-relaxed text-ink-muted">
          <Svg d={I.info} className="mt-0.5 shrink-0" />
          <p className="m-0">
            Certaines connexions sont déclarées dans le fichier <b className="font-medium text-ink-body">.env</b>
            {state.env_file ? ` (${state.env_file})` : ''} : elles s'ajoutent à celles de cet écran et ne sont modifiables que dans ce fichier.
          </p>
        </div>
      )}
      {notice && !editing && (
        <p role="status" className="m-0 rounded-lg bg-success-soft px-4 py-3 text-sm text-success-text">{notice}</p>
      )}
      {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-4 py-3 text-sm text-danger-text">{error}</p>}

      {editing === 'new' && <ConnectionEditor existing={null} onSaved={saved} onCancel={() => setEditing(null)} />}

      <section aria-labelledby="connexions-h" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="connexions-h" className="m-0 text-[19px] font-bold">Connexions aux modèles</h2>
          {editing !== 'new' && (
            <button type="button" onClick={() => { setEditing('new'); setNotice(null); }}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border-none bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-hover">
              <Svg d={I.plus} /> Ajouter une connexion
            </button>
          )}
        </div>
        {state.connections.length === 0 && editing !== 'new' && (
          <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-line-dashed bg-surface px-6 py-8">
            <p className="m-0 font-semibold">Aucune connexion</p>
            <p className="m-0 text-sm text-ink-muted">Ajoutez la passerelle fournie par votre service informatique, ou un modèle sur ce poste, pour lancer des analyses.</p>
          </div>
        )}
        {state.connections.map((c) =>
          editing === c.id && editingConnection ? (
            <ConnectionEditor key={c.id} existing={editingConnection} onSaved={saved} onCancel={() => setEditing(null)} />
          ) : (
            <ConnectionCard key={c.id} c={c} onEdit={() => { setEditing(c.id); setNotice(null); }} onDelete={() => remove(c)} onTested={(t) => tested(c.id, t)} />
          ),
        )}
      </section>

      <div className="flex gap-3 rounded-[10px] border border-line bg-surface px-5 py-4">
        <Svg d={I.info} className="mt-0.5 shrink-0 text-ink-muted" />
        <p className="m-0 text-[13px] leading-relaxed text-ink-muted">
          Connexions enregistrées dans <b className="font-medium text-ink-body">{state.storage_dir}</b> ; les clés sont chiffrées avec votre compte Windows. Pour un déploiement sur plusieurs postes, les fournisseurs déclarés dans un fichier <b className="font-medium text-ink-body">.env</b> s'ajoutent à cet écran.
        </p>
      </div>
    </main>
  );
};
