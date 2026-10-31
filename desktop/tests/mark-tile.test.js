'use strict';
// The quick bar sits on the desktop all day, and its icon had a black square
// behind it. That square is the mark's own tile: a near-black rounded rect
// inside the <symbol>, which on an already-dark pill is just a black block.
//
// It cannot simply be deleted. The blades are white-to-lavender gradients, so
// on the light theme they need something dark behind them or they vanish. So
// the tile became a theme token: absent on dark, present on light.
//
// The subtlety worth pinning is WHERE that token is read. The mark is drawn
// through <use>, and a selector outside that tree does not match inside it -
// `.mark .mk-tile { fill: ... }` reads as correct, matches nothing, and leaves
// the black square exactly where it was. (It did. That was the first attempt.)
// What crosses the boundary is inheritance, so the var() has to sit on the rect
// itself, inside the symbol. These tests fail if anyone moves it back out.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const here = (...p) => path.join(__dirname, '..', 'src', 'renderer', ...p);
const tokens = fs.readFileSync(here('tokens.css'), 'utf8');
const PAGES = ['quickbar.html', 'index.html'];
const SHEETS = ['quickbar.css', 'styles.css'];

test('the tile reads its fill from a theme token, without an inline style the CSP would block', () => {
  // A style="" attribute looked right and never applied: the pages' CSP is
  // style-src 'self', so Chromium dropped it and logged an error on every load.
  for (const page of PAGES) {
    const html = fs.readFileSync(here(page), 'utf8');
    assert.ok(/<rect class="mk-tile"[^>]*>/.test(html), `${page} no longer has the mk-tile rect`);
    assert.doesNotMatch(html, /\sstyle="/, `${page}: inline style attributes are blocked by the CSP`);
  }
  assert.match(tokens, /(^|\n)\.mk-tile\s*\{\s*fill:\s*var\(--mk-tile-fill/, 'tokens.css has no top-level .mk-tile rule reading the token');
});

test('the rect keeps a plain fill attribute as the fallback', () => {
  // If the stylesheet fails to load, a mark with no tile at all would be an
  // invisible icon on a light surface. The attribute is the floor.
  for (const page of PAGES) {
    const html = fs.readFileSync(here(page), 'utf8');
    const rect = /<rect class="mk-tile"[^>]*>/.exec(html)[0];
    assert.match(rect, /\bfill="#[0-9A-Fa-f]{6}"/, `${page}: no fallback fill attribute on the tile`);
  }
});

test('the dark themes drop the tile and the light theme keeps one', () => {
  const decls = [...tokens.matchAll(/--mk-tile-fill:\s*([^;]+);/g)].map((m) => m[1].trim());
  assert.ok(decls.length >= 2, 'the tile token is not declared per theme');
  assert.ok(decls.includes('transparent'), 'no theme drops the tile, so the black square survives on dark');
  assert.ok(
    decls.some((v) => /^#[0-9A-Fa-f]{6}$/.test(v)),
    'no theme keeps a tile, so the pale blades have nothing behind them on light',
  );
});

test('nobody tries to style the tile from outside the <use> tree again', () => {
  for (const sheet of SHEETS) {
    const css = fs.readFileSync(here(sheet), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ');            // the comments explain this very trap
    assert.doesNotMatch(
      css, /\.(mark|brand-mark)\s+\.mk-tile\s*\{/,
      `${sheet}: a descendant rule for .mk-tile cannot match inside <use> and will silently do nothing`,
    );
  }
});
