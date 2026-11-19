import { Analysis } from './types';

/** Titre de l'onglet et notification du système : une longue analyse se suit sans garder la page sous les yeux. */

export const APP_TITLE = 'DocAnalyser';

export const canNotify = () => typeof window !== 'undefined' && 'Notification' in window;

export const notifyPermission = (): NotificationPermission | 'unsupported' =>
  canNotify() ? Notification.permission : 'unsupported';

export const askNotifyPermission = async (): Promise<NotificationPermission | 'unsupported'> => {
  if (!canNotify()) return 'unsupported';
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
};

export const runningTitle = (a: Pick<Analysis, 'progress'>) => `${a.progress} % · Analyse en cours · ${APP_TITLE}`;

export const finishedTitle = (a: Pick<Analysis, 'status'>) =>
  a.status === 'done'
    ? `✓ Synthèse prête · ${APP_TITLE}`
    : a.status === 'failed'
      ? `Analyse échouée · ${APP_TITLE}`
      : APP_TITLE;

/** Notification de fin, seulement si l'utilisateur l'a autorisée et ne regarde pas déjà DocAnalyser. */
export const notifyFinished = (a: Analysis, onClick: () => void): void => {
  if (!canNotify() || Notification.permission !== 'granted') return;
  if (!document.hidden && document.hasFocus()) return;
  if (a.status !== 'done' && a.status !== 'failed') return;
  try {
    const n = new Notification(a.status === 'done' ? 'Votre synthèse est prête' : 'L’analyse a échoué', {
      body: a.status === 'done' ? a.title || a.mode_label : (a.error ?? '').slice(0, 180),
      tag: `docanalyser-${a.id}`,
    });
    n.onclick = () => {
      window.focus();
      onClick();
      n.close();
    };
  } catch {
    /* notifications refusées par le navigateur */
  }
};
