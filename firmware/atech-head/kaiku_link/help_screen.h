// help_screen: lays the three help lines (helpline.h) out on the eyes display, each as large as it fits.
// Plain layout code with one hook, so the same file draws on the standalone's canvas, through the MQTT firmware's
// HeadIO and in bench/speaker_pcm, and can be checked on a computer (firmware/atech-head/tests/test_helpline.py
// compiles it and checks that every row is inside the screen, for the upright 80 x 160 and the 160 x 80 layout).
//
// The screen is cut into three bands, top to bottom: name 16 %, helpline number 52 %, emergency number 32 %.
// In each band the text is broken at its spaces into rows and drawn at the largest font size at which every word
// fits a row and the rows fit the band (the driver's built-in font: 6 x 8 pixels a character at size 1).
// With today's lines: upright screen = name at size 1 on two rows, the helpline number at size 3 with one group of
// digits a row, the emergency number at size 4; wide screen = name size 1, helpline number size 2 on one row,
// emergency number size 3 (the test asserts these sizes, so a longer line that shrinks them is noticed).
// NOT seen on the real display: how readable that is at arm's length is for the bench to tell.
#pragma once

#include <stdint.h>
#include <string.h>

#include "helpline.h"

namespace help_screen {

constexpr int CHAR_W = 6, CHAR_H = 8;        // one character cell at size 1 (Adafruit GFX classic font)
constexpr int MARGIN = 2;                    // pixels kept free left and right
constexpr int MAX_ROWS = 4, ROW_CAP = 28;    // rows a line may break into; characters a row may hold (+ NUL)
constexpr int NAME_PCT = 16, NUMBER_PCT = 52;                 // band heights; the emergency number gets the rest
constexpr int NAME_MAX_SIZE = 2, NUMBER_MAX_SIZE = 4, EMERGENCY_MAX_SIZE = 5;
constexpr uint16_t NAME_COLOR = 0xC618;      // RGB565 light grey
constexpr uint16_t NUMBER_COLOR = 0xFFFF;    // white
constexpr uint16_t EMERGENCY_COLOR = 0xFE60; // amber

typedef void (*TextFn)(const char* text, int x, int y, int size, uint16_t color);   // one row, top-left at x, y

// Breaks `text` at its spaces into rows of at most `maxChars`. Returns the number of rows, or 0 when a word is
// longer than a row or more than MAX_ROWS would be needed.
inline int wrap(const char* text, int maxChars, char rows[MAX_ROWS][ROW_CAP]) {
  if (maxChars > ROW_CAP - 1) maxChars = ROW_CAP - 1;
  int n = 0, len = 0;   // rows used; characters in the last one
  const char* p = text;
  while (*p) {
    while (*p == ' ') p++;
    const char* word = p;
    while (*p && *p != ' ') p++;
    int wl = (int)(p - word);
    if (!wl) break;
    if (wl > maxChars) return 0;
    if (n && len + 1 + wl <= maxChars) {
      rows[n - 1][len++] = ' ';
    } else {
      if (n == MAX_ROWS) return 0;
      n++;
      len = 0;
    }
    memcpy(rows[n - 1] + len, word, (size_t)wl);
    len += wl;
    rows[n - 1][len] = 0;
  }
  return n;
}

// Draws `text` centred in the band y0 .. y0 + h of a w-pixel-wide screen, at the largest size up to `maxSize` that
// fits. Returns the size used; 0 = a word is wider than the screen even at size 1 (then nothing is drawn).
inline int fit(const char* text, int w, int y0, int h, int maxSize, uint16_t color, TextFn draw) {
  char rows[MAX_ROWS][ROW_CAP];
  for (int s = maxSize; s >= 1; s--) {
    int n = wrap(text, (w - 2 * MARGIN) / (CHAR_W * s), rows);
    int need = n * CHAR_H * s + (n - 1) * s;   // rows + a gap of `s` pixels between them
    if (!n || (need > h && s > 1)) continue;   // at size 1 it is drawn even if the band is too low: better than nothing
    int y = y0 + (h - need) / 2;
    if (y < y0) y = y0;
    for (int i = 0; i < n; i++) {
      int tw = (int)strlen(rows[i]) * CHAR_W * s - s;   // the last character's spacing column is not ink
      draw(rows[i], (w - tw) / 2, y + i * (CHAR_H * s + s), s, color);
    }
    return s;
  }
  return 0;
}

// The whole help screen on a w x h display that the caller has already cleared to black.
inline void draw(int w, int h, TextFn text) {
  int nameH = h * NAME_PCT / 100, numberH = h * NUMBER_PCT / 100;
  fit(HELPLINE_NAME, w, 0, nameH, NAME_MAX_SIZE, NAME_COLOR, text);
  fit(HELPLINE_NUMBER, w, nameH, numberH, NUMBER_MAX_SIZE, NUMBER_COLOR, text);
  fit(EMERGENCY_NUMBER, w, nameH + numberH, h - nameH - numberH, EMERGENCY_MAX_SIZE, EMERGENCY_COLOR, text);
}

}  // namespace help_screen
