import { expect, test } from '@playwright/test';

test('approfondir un thème puis revenir à la version précédente', async ({ page }) => {
  await page.goto('/#/analyse/e2e-demo/synthese');
  await page.getByRole('button', { name: 'Approfondir ce thème' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Approfondissement en cours' })).toBeVisible();

  await expect(page.getByText('Le lien envoyé par SMS désoriente')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/· approfondi/)).toBeVisible();
  // « Sept participants. » de l'ancienne version est toujours là (repris par la nouvelle)
  await expect(page.getByText('Sept participants arrivent par le simulateur')).toBeVisible();
  await page.screenshot({ path: process.env.SHOT ?? 'test-results/approfondi.png', fullPage: true });

  await page.getByRole('button', { name: 'Revenir à la version précédente' }).click();
  await expect(page.getByText('Le lien envoyé par SMS désoriente')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Approfondir ce thème' })).toBeVisible();
});
