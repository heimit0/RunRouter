import { test, expect } from '@playwright/test'

/**
 * Echter End-to-End-Test gegen das laufende Backend + öffentliches
 * OSRM/Nominatim. Externe Dienste können schwanken — daher separates Projekt
 * (`npm run e2e:real`), nicht Teil des Default-Testlaufs.
 */
test('generiert echte Routen gegen OSRM', async ({ page }) => {
  test.setTimeout(150_000)

  await page.goto('/')
  await expect(page.locator('h1')).toHaveText('RunRouter')

  // Startpunkt in der Berlin-Defaultansicht setzen (Kartenmitte).
  await page.locator('#map').click({ position: { x: 500, y: 350 } })
  await expect(page.locator('.leaflet-marker-icon')).toHaveCount(1)

  await page.click('#generate')

  // Route-Generierung braucht mehrere OSRM-Rundtrips — großzügiges Timeout.
  await expect(page.locator('.route-card').first()).toBeVisible({ timeout: 120_000 })

  const count = await page.locator('.route-card').count()
  expect(count).toBeGreaterThanOrEqual(1)

  // Jede Karte zeigt eine Distanz und einen GPX-Link.
  const meta = await page.locator('.route-card .meta').first().textContent()
  expect(meta).toMatch(/km/)
  await expect(page.locator('.route-card .gpx').first()).toHaveAttribute(
    'href',
    /\/api\/routes\/.+\/gpx/
  )
})
