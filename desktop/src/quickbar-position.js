'use strict';
// Where the quick bar sits.
//
// Pulled out of main.js so it can be tested without an Electron window, because
// the failure that matters here is silent: a position saved on a monitor that is
// no longer plugged in, or a bar dragged past the edge of the screen, leaves it
// somewhere the person cannot grab it to bring it back.

/** Centred at the top of the work area: where the bar lives until it is moved. */
function defaultBounds(size, workArea) {
  return {
    x: Math.round(workArea.x + (workArea.width - size.w) / 2),
    y: workArea.y + 10,
    width: size.w,
    height: size.h,
  };
}

/** A saved position, kept fully on screen. */
function clampBounds(pos, size, workArea) {
  if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) return defaultBounds(size, workArea);
  // When the display is narrower than the bar, the left edge wins: a bar whose
  // left edge is off screen cannot be grabbed at all.
  const maxX = Math.max(workArea.x, workArea.x + workArea.width - size.w);
  const maxY = Math.max(workArea.y, workArea.y + workArea.height - size.h);
  return {
    x: Math.min(Math.max(Math.round(pos.x), workArea.x), maxX),
    y: Math.min(Math.max(Math.round(pos.y), workArea.y), maxY),
    width: size.w,
    height: size.h,
  };
}

module.exports = { defaultBounds, clampBounds };
