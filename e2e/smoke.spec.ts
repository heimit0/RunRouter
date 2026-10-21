import { test, expect } from '@playwright/test'

/**
 * Deterministischer UI-Test: /api/*-Aufrufe werden im Browser gemockt, damit
 * kein OSRM/Nominatim/Overpass nötig ist. Prüft die Kern-UI-Flows.
 */

const ROUTES = {
  start: { lat: 52.5145, lon: 13.35 },
  length_km: 5,
  routes: [
    {
      id: 'r1',
      name: 'Route 1',
      distance_km: 5.2,
      duration_min: 30.0,
      green_score: 0.25,
      coordinates: [
        [52.5145, 13.35],
        [52.52, 13.356],
        [52.525, 13.35],
        [52.52, 13.344],
        [52.5145, 13.35],
      ],
      gpx_url: '/api/routes/r1/gpx',
    },
    {
      id: 'r2',
      name: 'Route 2',
      distance_km: 4.7,
      duration_min: 27.0,
      green_score: 0.0,
      coordinates: [
        [52.5145, 13.35],
        [52.509, 13.356],
        [52.505, 13.35],
        [52.509, 13.344],
        [52.5145, 13.35],
      ],
      gpx_url: '/api/routes/r2/gpx',
    },
  ],
}

async function mockApi(page) {
  await page.route('**/api/geocode**', (route) =>
    route.fulfill({ json: { results: [] } })
  )
  await page.route('**/api/routes**', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ json: ROUTES })
    }
    return route.continue()
  })
}

test('lädt Karte und generiert Routen', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await expect(page.locator('h1')).toHaveText('RunRouter')
  await expect(page.locator('#map')).toBeVisible()

  // Startpunkt per Klick in die Karte setzen
  await page.locator('#map').click({ position: { x: 400, y: 300 } })
  await expect(page.locator('.leaflet-marker-icon')).toHaveCount(1)

  await page.click('#generate')

  await expect(page.locator('.route-card')).toHaveCount(2)
  await expect(page.locator('.status')).toContainText('Routen gefunden')

  const firstGpx = page.locator('.route-card .gpx').first()
  await expect(firstGpx).toHaveAttribute('href', '/api/routes/r1/gpx')
  await expect(page.locator('.route-card .meta').first()).toContainText('5.2 km')
})

test('zeigt Fehler ohne Startpunkt', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await page.click('#generate')
  await expect(page.locator('.status')).toContainText('Startpunkt')
  await expect(page.locator('.route-card')).toHaveCount(0)
})

test('Längen-Slider aktualisiert das Label', async ({ page }) => {
  await page.goto('/')
  await page.locator('#length').fill('12')
  await expect(page.locator('#length-label')).toHaveText('12 km')
})
