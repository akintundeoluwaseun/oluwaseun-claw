// Does any example card on the home screen clip its own text?
//   node tests/idea-cards.mjs            # all widths, non-zero exit if anything clips
//
// This is the measurement, not an approximation of it: it loads the real
// index.html in Chromium, reads each .idea-eg's scrollHeight against its
// clientHeight, and reports the ones the two-line clamp is cutting off.
//
// Why it exists: the home column is capped at 780px, and the three-column grid
// divides that into 253px cards whose text column is 177px - about 25
// characters a line, so 50 for the two lines the clamp allows. Every one of the
// six examples was 58 to 70 characters, so every card on the default window was
// showing half a sentence and an ellipsis. Nothing about that is visible in the
// markup, and widening the window does not fix it, because the cap does not
// move. It needed measuring.
//
// Not in `npm test`: that suite is pure Node and must run anywhere. This needs
// a browser, so it is run by hand, like showcase.mjs and e2e.mjs.
import { chromium } from 'playwright-core';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const page = `file://${path.resolve(here, '..', 'src', 'renderer', 'index.html')}`;
const EXE = process.env.CLAW_CHROMIUM || '/opt/pw-browsers/chromium';

const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--headless'] });
let clipped = 0;
try {
  for (const width of [1440, 1280, 1100, 1000, 900, 820]) {
    const p = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    await p.goto(page);
    await p.waitForSelector('.idea-eg');
    const rows = await p.$$eval('.idea', (cards) => cards.map((c) => {
      const eg = c.querySelector('.idea-eg');
      const lh = parseFloat(getComputedStyle(eg).lineHeight);
      return {
        name: c.querySelector('.idea-name').textContent,
        text: eg.textContent.trim(),
        column: Math.round(eg.getBoundingClientRect().width),
        lines: Math.round(eg.scrollHeight / lh),
        clipped: eg.scrollHeight - eg.clientHeight > 1,
      };
    }));
    console.log(`\n${width}px window — ${rows.length} cards, ${rows[0].column}px text column`);
    for (const r of rows) {
      if (r.clipped) clipped += 1;
      console.log(`  ${r.clipped ? 'CLIPPED' : 'ok     '} ${r.name.padEnd(9)} ${String(r.text.length).padStart(3)} chars, ${r.lines} line(s)  ${r.text}`);
    }
    await p.close();
  }
} finally {
  await browser.close();
}
console.log(clipped ? `\n${clipped} card(s) clipped.` : '\nNo card clips its text at any width.');
process.exit(clipped ? 1 : 0);
