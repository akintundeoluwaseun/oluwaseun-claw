'use strict';
// Who made this, in one place.
//
// The name, the site and the copyright line appear in the app, in the Windows
// installer and in the packaged application's own properties. Three copies of a
// URL is three chances for one of them to rot, so everything that can read
// JavaScript reads it from here, and tests/creator.test.js checks that the one
// copy that cannot - the Settings markup - still matches.

const CREATOR = {
  name: 'Oluwaseun',
  // The full name as it appears in LICENSE, which is what a copyright line needs.
  holder: 'Akintunde Oluwaseun Joshua',
  site: 'https://oluwaseun-joshua-site.vercel.app/',
  // A WhatsApp username, not a phone number. It is shown and copied rather than
  // linked: a wa.me link expects a number, and a link that quietly fails is
  // worse than a name you can paste into WhatsApp's search yourself.
  whatsapp: 'oluwaseun85148',
  year: 2026,
};

CREATOR.copyright = `Copyright © ${CREATOR.year} ${CREATOR.holder}`;

/** Links the app may hand to the system browser. An allowlist, not a pattern. */
const ALLOWED_LINKS = [CREATOR.site];

function isAllowedLink(url) {
  if (typeof url !== 'string') return false;
  // Compared as parsed URLs, so a trailing slash or a different case in the host
  // does not decide it, and a lookalike host cannot sneak past a string compare.
  let candidate;
  try {
    candidate = new URL(url);
  } catch {
    return false;
  }
  if (candidate.protocol !== 'https:') return false;
  return ALLOWED_LINKS.some((allowed) => {
    const known = new URL(allowed);
    return known.origin === candidate.origin
      && known.pathname.replace(/\/$/, '') === candidate.pathname.replace(/\/$/, '');
  });
}

module.exports = { CREATOR, ALLOWED_LINKS, isAllowedLink };
