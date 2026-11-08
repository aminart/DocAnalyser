import { expect, test } from '@playwright/test';

test('historique puis synthèse d’une analyse terminée', async ({ page }) => {
  await page.goto('/#/historique');
  await page.getByText('Ouverture de compte').click();
  await expect(page).toHaveURL(/#\/analyse\/e2e-demo\/synthese$/);
  await expect(page.getByRole('heading', { name: 'Ouverture de compte', level: 1 })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Synthèse' })).toHaveAttribute('aria-selected', 'true');
});

test('question sur les documents : réponse au fil de l’eau, sources vérifiables', async ({ page }) => {
  await page.goto('/#/analyse/e2e-demo/synthese');
  await page.getByRole('tab', { name: /Questions/ }).click();
  await expect(page).toHaveURL(/\/questions$/);

  const input = page.getByLabel('Votre question');
  await input.fill('D’où viennent les participants ?');
  await input.press('Enter');

  await expect(page.getByText('D’où viennent les participants ?')).toBeVisible();
  await expect(page.getByText('Réponse fondée sur l’ensemble des documents.')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/simulateur de tarif/)).toBeVisible();
  await expect(page.getByText('Une source citée est introuvable', { exact: false })).toBeVisible();

  // La source ouvre le passage d'origine, ligne surlignée
  await page.getByRole('button', { name: /parcours L16/ }).click();
  const panel = page.getByRole('dialog');
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/2 participants ont abandonné/)).toBeVisible();
  await panel.getByRole('button', { name: 'Fermer le panneau' }).click();

  // La question est enregistrée avec l'analyse
  await page.reload();
  await expect(page.getByText('D’où viennent les participants ?')).toBeVisible();
  await expect(page.getByRole('tab', { name: /Questions/ })).toContainText('1');
});
