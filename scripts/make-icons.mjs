// Render app/icons/icon.svg to the PNG sizes the manifest and iOS need.
// Uses Playwright's Chromium (with the bundled Devanagari font). Run once
// after changing the SVG:  node scripts/make-icons.mjs
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const { chromium } = createRequire(import.meta.url)('playwright');
const ROOT = new URL('..', import.meta.url).pathname;
const font = readFileSync(`${ROOT}app/fonts/noto-serif-devanagari-deva.woff2`).toString('base64');
const svg = readFileSync(`${ROOT}app/icons/icon.svg`, 'utf8');
const browser = await chromium.launch();
const page = await browser.newPage();
for (const [name, size, pad, bg] of [
  ['icon-192.png', 192, 0, null], ['icon-512.png', 512, 0, null],
  ['apple-touch-icon.png', 180, 0, '#7a2e1d'], ['icon-maskable-512.png', 512, 0.12, '#7a2e1d'],
]) {
  // Maskable icons need the artwork inside the central safe zone; iOS
  // touch icons must not be transparent, so both get a full background.
  const inner = Math.round(size * (1 - 2 * pad));
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<style>@font-face{font-family:'Noto Serif Devanagari';font-weight:100 900;
    src:url(data:font/woff2;base64,${font})}html,body{margin:0;background:${bg || 'transparent'}}
    div{width:${size}px;height:${size}px;display:grid;place-items:center}svg{width:${inner}px;height:${inner}px}</style>
    <div>${svg}</div>`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${ROOT}app/icons/${name}`, omitBackground: !bg });
}
await browser.close();
console.log('icons written');
