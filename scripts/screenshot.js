#!/usr/bin/env node
// EdgeFinder — Headless screenshot utility for Claude Code
// Usage: NODE_PATH=$(npm root -g) node scripts/screenshot.js [page] [output]
//
// Pages: chat, dashboard, simulation, briefing, journal, settings, guide, ticker/:sym
// Default: chat → /tmp/screenshot.png
//
// Examples:
//   NODE_PATH=$(npm root -g) node scripts/screenshot.js chat /tmp/chat.png
//   NODE_PATH=$(npm root -g) node scripts/screenshot.js dashboard /tmp/dash.png
//   NODE_PATH=$(npm root -g) node scripts/screenshot.js ticker/NVDA /tmp/nvda.png
//   NODE_PATH=$(npm root -g) node scripts/screenshot.js all /tmp/  # screenshots all pages

const { chromium } = require('playwright')

const BASE = 'https://trust-index-cyan.vercel.app'
const CREDS = { email: 'test@email.com', password: 'screenshot2026' }
const VIEWPORT = { width: 1536, height: 768 }

const PAGES = {
  chat: '/chat',
  dashboard: '/',
  simulation: '/simulation',
  briefing: '/briefing',
  journal: '/journal',
  settings: '/settings',
  guide: '/guide',
}

async function login(page) {
  await page.goto(`${BASE}/login`)
  await page.waitForTimeout(1500)
  await page.fill('input[type="email"]', CREDS.email)
  await page.fill('input[type="password"]', CREDS.password)
  await page.click('button[type="submit"]')
  await page.waitForTimeout(3000)

  if (page.url().includes('/login')) {
    throw new Error('Login failed — still on login page')
  }
  console.log('Logged in successfully')
}

async function screenshotPage(page, pageName, outputPath) {
  let route = PAGES[pageName]
  if (!route && pageName.startsWith('ticker/')) {
    const sym = pageName.split('/')[1]
    route = `/tickers/${sym}`
  }
  if (!route) {
    console.error(`Unknown page: ${pageName}. Available: ${Object.keys(PAGES).join(', ')}, ticker/:sym`)
    process.exit(1)
  }

  await page.goto(`${BASE}${route}`)
  await page.waitForTimeout(2500)
  await page.screenshot({ path: outputPath })
  console.log(`${pageName} → ${outputPath}`)
}

;(async () => {
  const args = process.argv.slice(2)
  const pageName = args[0] || 'chat'
  const output = args[1] || '/tmp/screenshot.png'

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: VIEWPORT })

  try {
    await login(page)

    if (pageName === 'all') {
      const dir = output.endsWith('/') ? output : output + '/'
      for (const [name] of Object.entries(PAGES)) {
        await screenshotPage(page, name, `${dir}${name}.png`)
      }
    } else {
      await screenshotPage(page, pageName, output)
    }
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error('Error:', e.message)
  process.exit(1)
})
