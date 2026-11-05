// Does the quick bar resolve to a transparent canvas in every theme?
//   node tests/quickbar-transparency.mjs      # non-zero exit if any combination is opaque
//
// This is the measurement, not an approximation of it. The quick bar is a
// transparent, frameless Electron window; when `color-scheme` resolves to dark
// or light, Chromium composites its own opaque canvas underneath and the bar
// arrives as a black rectangle (or a white one in light mode) with a rounded
// pill drawn inside it. Photographed on a red desktop, 5 November, and reported
// repeatedly before that.
//
// The first fix wrote `html { color-scheme: normal }` and did nothing, because
// `html` is a type selector (0-0-1) and tokens.css uses `:root` (a pseudo-class,
// 0-1-0) and `:root[data-theme="dark"]` (0-2-0). It lost every time. Nothing in
// the source made that visible - only computing the cascade does, which is what
// this script is for.
//
// Not in `npm test`: that suite is pure Node and must run anywhere. This needs
// a browser, like idea-cards.mjs and showcase.mjs.
import { chromium } from 'playwright-core';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const page = `file://${path.resolve(here, '..', 'src', 'renderer', 'quickbar.html')}`;
const EXE = process.env.CLAW_CHROMIUM || '/opt/pw-browsers/chromium';

const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--headless'] });
let bad = 0;
try {
  console.log('theme      Windows is  color-scheme  html background     body background');
  for (const scheme of ['dark', 'light']) {
    for (const theme of ['(not set)', 'dark', 'light']) {
      const p = await browser.newPage({ colorScheme: scheme });
      await p.goto(page);
      if (theme !== '(not set)') {
        await p.evaluate((t) => { document.documentElement.dataset.theme = t; }, theme);
      }
      await p.waitForSelector('.pill');
      const r = await p.evaluate(() => ({
        cs: getComputedStyle(document.documentElement).colorScheme,
        html: getComputedStyle(document.documentElement).backgroundColor,
        body: getComputedStyle(document.body).backgroundColor,
      }));
      const clear = (c) => c === 'rgba(0, 0, 0, 0)' || c === 'transparent';
      const ok = r.cs === 'normal' && clear(r.html) && clear(r.body);
      if (!ok) bad += 1;
      console.log(`${ok ? 'ok    ' : 'OPAQUE'} ${theme.padEnd(10)} ${scheme.padEnd(11)} ${r.cs.padEnd(13)} ${r.html.padEnd(19)} ${r.body}`);
      await p.close();
    }
  }
} finally {
  await browser.close();
}
console.log(bad
  ? `\n${bad} of 6 combinations would paint a solid rectangle behind the bar.`
  : '\nAll 6 combinations resolve to a transparent canvas.');
process.exit(bad ? 1 : 0);
