// The T-Dongle-S3's 160x80 screen: what it shows and how it's drawn. Drawing goes to an
// off-screen canvas that's copied to the screen in one go, so nothing flickers.
//
// Page 1: state of charge, bar, time left and status on the left; voltage, current, power and
//         consumed Ah on the right.
// Page 2: the aux input (starter / midpoint / temperature), signal, last update and the model.
// The BOOT button switches pages.
#pragma once
#include <Arduino_GFX_Library.h>
#include "fonts.h"

// Same colours as the other versions (RGB565)
static const uint16_t C_BG = RGB565(14, 17, 22), C_TEXT = RGB565(235, 238, 243), C_MUTED = RGB565(140, 150, 165),
                      C_GREEN = RGB565(60, 200, 120), C_AMBER = RGB565(240, 180, 50), C_RED = RGB565(230, 70, 70),
                      C_LINE = RGB565(42, 49, 60);

struct DongleState {
  char soc[6] = "--";                // "77"
  uint16_t socColor = C_MUTED;
  float bar = -1;                    // %, < 0 = empty
  char time[14] = "--";              // "20h 34m", "Charging", "Full"
  char volt[12] = "--", amps[12] = "--", watts[12] = "--", cons[12] = "--";
  uint16_t valColor = C_MUTED, curColor = C_MUTED;
  char auxLabel[10] = "Aux", aux[12] = "--", signal[12] = "--", age[16] = "--", model[14] = "SmartShunt";
  char status[12] = "Searching";
  uint16_t statusColor = C_AMBER;
};

// Text helpers. align: 0 left, 1 centre, 2 right (x is the right edge). Falls back to `smaller`
// if the text is wider than maxW.
static void scrText(Arduino_GFX *g, const char *s, int x, int baseline, const GFXfont *f, uint16_t col, int align = 0,
                    int maxW = 0, const GFXfont *smaller = nullptr) {
  int16_t bx, by; uint16_t bw, bh;
  g->setFont(f);
  g->getTextBounds(s, 0, 0, &bx, &by, &bw, &bh);
  if (maxW && bw > maxW && smaller) {
    g->setFont(smaller);
    g->getTextBounds(s, 0, 0, &bx, &by, &bw, &bh);
  }
  g->setTextColor(col);
  g->setCursor(align == 0 ? x : align == 1 ? x - (int)bw / 2 - bx : x - (int)bw - bx, baseline);
  g->print(s);
}

static int scrWidth(Arduino_GFX *g, const char *s, const GFXfont *f) {
  int16_t bx, by; uint16_t bw, bh;
  g->setFont(f);
  g->getTextBounds(s, 0, 0, &bx, &by, &bw, &bh);
  return bx + bw;
}

static void drawPage1(Arduino_GFX *g, const DongleState &s) {
  g->fillScreen(C_BG);
  // state of charge: big number, small %
  int w = scrWidth(g, s.soc, &FontBig);
  scrText(g, s.soc, 3, 31, &FontBig, s.socColor);
  if (strcmp(s.soc, "--")) scrText(g, "%", 3 + w + 2, 31, &FontMid, s.socColor);
  // bar
  g->fillRoundRect(4, 37, 70, 6, 3, C_LINE);
  if (s.bar > 0) {
    int px = (int)(70 * (s.bar > 100 ? 100 : s.bar) / 100.0f);
    g->fillRoundRect(4, 37, px < 6 ? 6 : px, 6, 3, s.socColor);
  }
  // time left / Charging / Full
  scrText(g, s.time, 4, 59, &FontMid, s.valColor, 0, 72, &FontSmall);
  // status
  g->fillCircle(7, 72, 3, s.statusColor);
  scrText(g, s.status, 14, 76, &FontSmall, s.statusColor, 0, 62);
  // divider and the four readings
  g->drawFastVLine(79, 4, 72, C_LINE);
  const char *vals[4] = {s.volt, s.amps, s.watts, s.cons};
  const uint16_t cols[4] = {s.valColor, s.curColor, s.curColor, s.valColor};
  for (int i = 0; i < 4; i++)
    scrText(g, vals[i], 157, 16 + i * 19, &FontMid, strcmp(vals[i], "--") ? cols[i] : C_MUTED, 2, 74, &FontSmall);
}

static void drawPage2(Arduino_GFX *g, const DongleState &s) {
  g->fillScreen(C_BG);
  const char *labels[4] = {s.auxLabel, "Signal", "Updated", "Monitor"};
  const char *vals[4] = {s.aux, s.signal, s.age, s.model};
  for (int i = 0; i < 4; i++) {
    int base = 16 + i * 19;
    if (i) g->drawFastHLine(4, base - 14, 152, C_LINE);
    scrText(g, labels[i], 4, base, &FontSmall, C_MUTED);
    scrText(g, vals[i], 157, base, &FontMid, strcmp(vals[i], "--") ? s.valColor : C_MUTED, 2, 100, &FontSmall);
  }
}

// A message: title and up to two lines (setup, no SD card...).
static void drawMessage(Arduino_GFX *g, const char *title, uint16_t col, const char *l1, const char *l2 = nullptr) {
  g->fillScreen(C_BG);
  scrText(g, title, 80, 26, &FontMid, col, 1, 156, &FontSmall);
  if (l1) scrText(g, l1, 80, 50, &FontSmall, C_TEXT, 1);
  if (l2) scrText(g, l2, 80, 66, &FontSmall, C_MUTED, 1);
}
