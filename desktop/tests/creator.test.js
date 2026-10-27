'use strict';
// The creator's details appear in six places: this module, the Settings markup,
// the installer, the packaged app's version resource, package.json, and LICENSE.
// Only the first can be imported, so these tests check the rest against it. A
// wrong link in a shipped installer is not something a user can fix.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { CREATOR, isAllowedLink } = require('../src/creator');
const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');

test('the About panel carries the username and a badge that is the link', () => {
  const html = read('src', 'renderer', 'index.html');
  assert.ok(html.includes(CREATOR.whatsapp), 'the WhatsApp username is not in the About panel');
  assert.ok(html.includes('id="credit-badge"'), 'the badge button is missing');
});

test('the address is never written on screen', () => {
  // The badge is the link: the URL lives in creator.js and is handed to the
  // browser, never printed in the panel. A second copy in the markup is also a
  // second copy to get wrong.
  const html = read('src', 'renderer', 'index.html');
  const host = new URL(CREATOR.site).host;
  assert.ok(!html.includes(host), `the markup still shows ${host}`);
});

test('the installer carries the publisher, the link and the copyright', () => {
  const iss = fs.readFileSync(path.join(__dirname, '..', '..', 'packaging', 'claw.iss'), 'utf8');
  assert.ok(iss.includes(`AppPublisherURL=${CREATOR.site}`), 'AppPublisherURL does not match');
  // Inno Setup's .iss is read as ANSI by older compilers, so the symbol is spelled (C).
  assert.ok(iss.includes(`AppCopyright=Copyright (C) ${CREATOR.year} ${CREATOR.holder}`),
    'AppCopyright does not match');
});

test('the packaged executable carries the copyright', () => {
  const builder = require('../electron-builder.config.js');
  assert.strictEqual(builder.copyright, CREATOR.copyright);
});

test('package.json names the author and the site', () => {
  const pkg = JSON.parse(read('package.json'));
  assert.strictEqual(pkg.author.name, CREATOR.holder);
  assert.strictEqual(pkg.homepage, CREATOR.site);
});

test('LICENSE holds the same copyright holder and year', () => {
  const licence = fs.readFileSync(path.join(__dirname, '..', '..', 'LICENSE'), 'utf8');
  assert.ok(licence.includes(`Copyright (c) ${CREATOR.year} ${CREATOR.holder}`),
    'LICENSE does not name the same holder and year');
});

test('only the creator\'s own site may be opened, and only over https', () => {
  assert.ok(isAllowedLink(CREATOR.site));
  assert.ok(isAllowedLink(CREATOR.site.replace(/\/$/, '')), 'a missing trailing slash is the same link');
  assert.ok(!isAllowedLink(CREATOR.site.replace('https', 'http')), 'http must not pass');
  assert.ok(!isAllowedLink('https://oluwaseun-joshua-site.vercel.app.evil.test/'), 'a lookalike host must not pass');
  assert.ok(!isAllowedLink('https://oluwaseun-joshua-site.vercel.app/admin'), 'another page must not pass');
  assert.ok(!isAllowedLink('file:///C:/Windows/System32/cmd.exe'));
  assert.ok(!isAllowedLink(''), 'empty is not a link');
  assert.ok(!isAllowedLink(null));
  assert.ok(!isAllowedLink({ toString: () => CREATOR.site }), 'only a string is a link');
});
