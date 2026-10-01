// Touch input, touch calibration and the on-screen settings pages.
// Included by ShuntDisplayR4.ino after its globals (tft, cfg, colours, fonts).
#pragma once

// ============================================================ touch hardware
// The resistive touch panel shares four pins with the screen: two digital data pins and two
// analog control pins. Which ones varies between shields, so they're found at start-up.
struct TouchHW { int8_t dA = -1, aA = -1, dB = -1, aB = -1; bool ok = false; } touchHW;

static void touchPinsIdle() {  // hand the pins back to the screen
  const int8_t p[4] = {touchHW.dA, touchHW.aA, touchHW.dB, touchHW.aB};
  for (int i = 0; i < 4; i++)
    if (p[i] >= 0) { pinMode(p[i], OUTPUT); digitalWrite(p[i], HIGH); }
}

// Call before the screen is started. Each touch layer joins one digital pin to one
// analog pin through a few hundred ohms, so pulling the digital pin low drags the
// (pulled-up) analog pin low with it.
static bool detectTouchPins() {
  const int8_t dig[4] = {6, 7, 8, 9};
  const int8_t ana[3] = {A1, A2, A3};
  pinMode(A0, OUTPUT); digitalWrite(A0, HIGH);  // screen RD idle: it never drives the bus
  int8_t pd[2], pa[2];
  int found = 0;
  for (int ai = 0; ai < 3; ai++) {
    int matches = 0; int8_t match = -1;
    for (int di = 0; di < 4; di++) {
      for (int k = 0; k < 4; k++) pinMode(dig[k], INPUT);
      for (int k = 0; k < 3; k++) pinMode(ana[k], INPUT_PULLUP);
      pinMode(dig[di], OUTPUT);
      digitalWrite(dig[di], LOW);  delayMicroseconds(300);
      bool lo = digitalRead(ana[ai]) == LOW;
      digitalWrite(dig[di], HIGH); delayMicroseconds(300);
      bool hi = digitalRead(ana[ai]) == HIGH;
      if (lo && hi) { matches++; match = dig[di]; }
    }
    if (matches == 1 && found < 2) { pd[found] = match; pa[found] = ana[ai]; found++; }
  }
  for (int k = 0; k < 4; k++) { pinMode(dig[k], OUTPUT); digitalWrite(dig[k], HIGH); }
  for (int k = 0; k < 3; k++) { pinMode(ana[k], OUTPUT); digitalWrite(ana[k], HIGH); }
  if (found == 2 && pd[0] != pd[1]) {
    touchHW.dA = pd[0]; touchHW.aA = pa[0]; touchHW.dB = pd[1]; touchHW.aB = pa[1];
    touchHW.ok = true;
  }
  return touchHW.ok;
}

// Is the screen being pressed? Ground layer A, pull layer B up: contact pulls B low.
static bool touchPressed() {
  if (!touchHW.ok) return false;
  pinMode(touchHW.dB, INPUT);
  pinMode(touchHW.aB, INPUT_PULLUP);
  pinMode(touchHW.dA, OUTPUT); digitalWrite(touchHW.dA, LOW);
  pinMode(touchHW.aA, OUTPUT); digitalWrite(touchHW.aA, LOW);
  delayMicroseconds(150);
  bool t = digitalRead(touchHW.aB) == LOW;
  touchPinsIdle();
  return t;
}

// Voltage divider reading along one layer, sensed through the other layer.
static int touchAlong(bool layerA) {
  int8_t d1 = layerA ? touchHW.dA : touchHW.dB, a1 = layerA ? touchHW.aA : touchHW.aB;
  int8_t d2 = layerA ? touchHW.dB : touchHW.dA, a2 = layerA ? touchHW.aB : touchHW.aA;
  pinMode(d2, INPUT); pinMode(a2, INPUT);
  pinMode(d1, OUTPUT); digitalWrite(d1, HIGH);
  pinMode(a1, OUTPUT); digitalWrite(a1, LOW);
  delayMicroseconds(150);
  int v[5];
  for (int i = 0; i < 5; i++) v[i] = analogRead(a2);
  for (int i = 1; i < 5; i++) for (int j = i; j > 0 && v[j] < v[j - 1]; j--) { int t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
  return v[2];  // median
}

static bool touchRaw(int &ra, int &rb) {
  if (!touchPressed()) return false;
  ra = touchAlong(true);
  rb = touchAlong(false);
  touchPinsIdle();
  return touchPressed();  // still pressed, so the reading is good
}

// Screen coordinates (320x240) of the current press.
static bool touchXY(int &x, int &y) {
  int ra, rb;
  if (!cfg.touchCalOk || !touchRaw(ra, rb)) return false;
  int rx = cfg.tSwap ? rb : ra, ry = cfg.tSwap ? ra : rb;
  x = (long)(rx - cfg.tx0) * 319 / (cfg.tx1 - cfg.tx0);
  y = (long)(ry - cfg.ty0) * 239 / (cfg.ty1 - cfg.ty0);
  if (cfg.tRot != cfg.rotation) { x = 319 - x; y = 239 - y; }  // rotated 180 since calibration
  x = constrain(x, 0, 319);
  y = constrain(y, 0, 239);
  return true;
}

static void waitRelease() {
  uint32_t t = millis();
  while (millis() - t < 120) { if (touchPressed()) t = millis(); delay(5); }
}

// Waits for a tap; returns its position. False on timeout.
static bool waitTap(int &x, int &y, uint32_t timeoutMs) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (touchXY(x, y)) {
      int x2, y2;
      delay(15);
      if (touchXY(x2, y2)) { x = (x + x2) / 2; y = (y + y2) / 2; }
      waitRelease();
      return true;
    }
    delay(10);
  }
  return false;
}

// ============================================================ drawing helpers
struct Btn { int16_t x, y, w, h; };
static bool hit(const Btn &b, int x, int y) { return x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h; }

// Text with its vertical centre at yc. align: 0 left, 1 centre, 2 right.
static void uiText(const char *s, int x, int yc, const GFXfont *f, uint16_t col, int align = 0) {
  tft->setFont(f);
  tft->setTextColor(col);
  int16_t bx, by; uint16_t bw, bh;
  tft->getTextBounds(s, 0, 0, &bx, &by, &bw, &bh);
  int cx = align == 0 ? x - bx : align == 1 ? x - (int)bw / 2 - bx : x - (int)bw - bx;
  tft->getTextBounds("0", 0, 0, &bx, &by, &bw, &bh);  // centre on digit height for a steady baseline
  tft->setCursor(cx, yc - by - (int)bh / 2);
  tft->print(s);
}

static void drawBtn(const Btn &b, const char *label, uint16_t bg, uint16_t fg, const GFXfont *f = &FontLabel) {
  tft->fillRoundRect(b.x, b.y, b.w, b.h, 6, bg);
  uiText(label, b.x + b.w / 2, b.y + b.h / 2, f, fg, 1);
}

static void uiMessage(const char *line1, const char *line2, uint16_t col) {
  tft->fillScreen(C_BG);
  uiText(line1, 160, 105, &FontVal, col, 1);
  if (line2) uiText(line2, 160, 140, &FontLabel, C_MUTED, 1);
}

// ============================================================ settings cog
// Centre of the cog in the top-right corner of the dashboard.
static const int COG_X = 304, COG_Y = 13;

static void drawCog(int cx, int cy, uint16_t col, uint16_t bg) {
  for (int i = 0; i < 8; i++) {                 // 8 teeth
    float a = i * PI / 4;
    tft->fillCircle(cx + cosf(a) * 8.5f, cy + sinf(a) * 8.5f, 2, col);
  }
  tft->fillCircle(cx, cy, 7, col);              // body
  tft->fillCircle(cx, cy, 3, bg);               // hole
}

// ============================================================ calibration
static void drawCross(int x, int y, uint16_t col) {
  tft->drawFastHLine(x - 12, y, 25, col);
  tft->drawFastVLine(x, y - 12, 25, col);
  tft->drawCircle(x, y, 6, col);
}

// Averages raw readings while the screen is held. False on timeout.
static bool calPoint(int x, int y, int &ra, int &rb) {
  tft->fillScreen(C_BG);
  uiText("Touch calibration", 160, 100, &FontValS, C_TEXT, 1);
  uiText("Tap the centre of the cross", 160, 128, &FontLabel, C_MUTED, 1);
  uiText("(a stylus or fingernail works best)", 160, 148, &FontSmall, C_MUTED, 1);
  drawCross(x, y, C_AMBER);
  waitRelease();
  uint32_t t0 = millis();
  while (!touchPressed()) { if (millis() - t0 > 30000) return false; delay(10); }
  long sa = 0, sb = 0; int n = 0;
  uint32_t t1 = millis();
  while (millis() - t1 < 250) {
    int a, b;
    if (touchRaw(a, b)) { sa += a; sb += b; n++; }
  }
  drawCross(x, y, C_GREEN);
  waitRelease();
  if (n < 3) return false;
  ra = sa / n; rb = sb / n;
  return true;
}

// Three taps: top-left, top-right, bottom-right. Saves the result to the SD card.
static bool runCalibration() {
  if (!touchHW.ok) return false;
  const int X1 = 30, X2 = 290, Y1 = 30, Y2 = 210;
  int a1, b1, a2, b2, a3, b3;
  if (!calPoint(X1, Y1, a1, b1) || !calPoint(X2, Y1, a2, b2) || !calPoint(X2, Y2, a3, b3)) {
    uiMessage("Calibration stopped", "no touch for 30 seconds", C_AMBER);
    delay(1500);
    return false;
  }
  // Which raw axis changed when moving across (x)?
  bool swap = abs(b2 - b1) > abs(a2 - a1);
  int rx1 = swap ? b1 : a1, rx2 = swap ? b2 : a2;
  int ry2 = swap ? a2 : b2, ry3 = swap ? a3 : b3;
  if (abs(rx2 - rx1) < 80 || abs(ry3 - ry2) < 80) {
    uiMessage("Calibration failed", "taps were too close together - try again", C_RED);
    delay(2000);
    return false;
  }
  float sx = (float)(rx2 - rx1) / (X2 - X1), sy = (float)(ry3 - ry2) / (Y2 - Y1);
  cfg.tSwap = swap;
  cfg.tx0 = rx1 - sx * X1;  cfg.tx1 = rx1 + sx * (319 - X1);
  cfg.ty0 = ry2 - sy * Y1;  cfg.ty1 = ry2 + sy * (239 - Y1);
  cfg.tRot = cfg.rotation;
  cfg.calChip = lcdChip == 8230 ? 2 : 1;
  cfg.touchCalOk = true;
  int saved = saveConfig(cfg);
  uiMessage("Touch calibrated", (saved & SAVED_SD) ? "saved to the SD card" : saved ? "saved in the display's memory"
                                                    : "couldn't be saved - lost at power-off", C_GREEN);
  delay(1200);
  return true;
}

// ============================================================ hex keypad (MAC / key)
// allowEmpty: OK with nothing typed returns "" (Clear, then OK removes an extra charger).
static bool hexEntry(const char *title, int len, char *digits /* len+1, in/out */, bool allowEmpty = false) {
  static const char *keys[20] = {"0", "1", "2", "3", "Del",
                                 "4", "5", "6", "7", "Clear",
                                 "8", "9", "a", "b", "Cancel",
                                 "c", "d", "e", "f", "OK"};
  char cur[33];
  strncpy(cur, digits, len); cur[len] = 0;
  int n = strlen(cur);

  tft->fillScreen(C_BG);
  uiText(title, 10, 14, &FontValXS, C_TEXT);
  for (int i = 0; i < 20; i++) {
    Btn b = {(int16_t)((i % 5) * 64 + 2), (int16_t)(80 + (i / 5) * 40), 60, 36};
    uint16_t bg = i % 5 == 4 ? (i == 19 ? C_GREEN : RGB565(60, 66, 78)) : C_PANEL;
    drawBtn(b, keys[i], bg, i == 19 ? C_BG : C_TEXT, i % 5 == 4 ? &FontLabel : &FontValS);
  }
  bool dirty = true;
  uint32_t lastAct = millis();
  while (true) {
    if (dirty) {
      char shown[48]; int k = 0;
      for (int i = 0; i < len; i++) {
        if (i && len == 12 && i % 2 == 0) shown[k++] = ':';
        if (i && len == 32 && i % 4 == 0) shown[k++] = ' ';
        shown[k++] = i < n ? cur[i] : '_';
      }
      shown[k] = 0;
      tft->fillRoundRect(5, 30, 310, 44, 8, C_PANEL);
      uiText(shown, 160, 52, len == 12 ? &FontValS : &FontLabel, C_TEXT, 1);
      char cnt[8]; snprintf(cnt, sizeof(cnt), "%d/%d", n, len);
      tft->fillRect(250, 2, 70, 24, C_BG);
      uiText(cnt, 312, 14, &FontLabel, n == len || (allowEmpty && !n) ? C_GREEN : C_MUTED, 2);
      dirty = false;
    }
    int x, y;
    if (!waitTap(x, y, 500)) { if (millis() - lastAct > 90000) return false; continue; }
    lastAct = millis();
    if (y < 80) continue;
    int i = ((y - 80) / 40) * 5 + x / 64;
    if (i < 0 || i >= 20) continue;
    if (i % 5 != 4) { if (n < len) { cur[n++] = keys[i][0]; cur[n] = 0; dirty = true; } }
    else if (i == 4)  { if (n) { cur[--n] = 0; dirty = true; } }   // Del
    else if (i == 9)  { n = 0; cur[0] = 0; dirty = true; }          // Clear
    else if (i == 14) return false;                                  // Cancel
    else if (i == 19 && (n == len || (allowEmpty && !n))) { strcpy(digits, cur); return true; }  // OK
  }
}

// ============================================================ settings pages
static const Btn B_CANCEL = {5, 200, 72, 36}, B_PREV = {82, 200, 48, 36},
                 B_NEXT = {190, 200, 48, 36}, B_SAVE = {243, 200, 72, 36};
static const int PAGES = 5;

static int rowY(int r) { return 30 + r * 42; }

// Screen timeout choices, in seconds (0 = never)
static const uint16_t SCREEN_OFF_STEPS[] = {0, 15, 30, 60, 120, 300, 600};
static const int N_SCREEN_OFF = sizeof(SCREEN_OFF_STEPS) / sizeof(SCREEN_OFF_STEPS[0]);
static int screenOffIndex(uint16_t s) {
  int best = 0;
  for (int i = 0; i < N_SCREEN_OFF; i++) if (SCREEN_OFF_STEPS[i] <= s) best = i;
  return best;
}

static void rowFrame(int r, const char *label) {
  tft->fillRoundRect(5, rowY(r), 310, 38, 8, C_PANEL);
  uiText(label, 15, rowY(r) + 19, &FontLabel, C_MUTED);
}
static void rowValue(int r, const char *label, const char *value, const GFXfont *f = &FontLabel) {
  rowFrame(r, label);
  uiText(value, 302, rowY(r) + 19, f, C_TEXT, 2);
}
static void rowToggle(int r, const char *label, const char *a, const char *b, bool second) {
  rowFrame(r, label);
  Btn b1 = {186, (int16_t)(rowY(r) + 5), 62, 28}, b2 = {250, (int16_t)(rowY(r) + 5), 62, 28};
  drawBtn(b1, a, second ? C_BG : C_GREEN, second ? C_MUTED : C_BG);
  drawBtn(b2, b, second ? C_GREEN : C_BG, second ? C_BG : C_MUTED);
}
static void rowStepper(int r, const char *label, int value, const char *unit) {
  rowFrame(r, label);
  Btn m = {186, (int16_t)(rowY(r) + 5), 36, 28}, p = {276, (int16_t)(rowY(r) + 5), 36, 28};
  drawBtn(m, "-", C_BG, C_TEXT, &FontValS);
  drawBtn(p, "+", C_BG, C_TEXT, &FontValS);
  char buf[12]; snprintf(buf, sizeof(buf), "%d%s", value, unit);
  uiText(buf, 249, rowY(r) + 19, &FontValXS, C_TEXT, 1);
}
// Which half of a toggle / stepper was tapped: -1 left, +1 right, 0 neither.
static int rowSide(int x) { return (x >= 186 && x < 250) ? -1 : (x >= 250) ? 1 : 0; }
static int stepSide(int x) { return (x >= 180 && x < 228) ? -1 : (x >= 268) ? 1 : 0; }

static const char *const SOURCE_NAMES[N_SOURCES] = {"Automatic", "DC-DC", "Solar", "Mains", "Alternator"};
static const char *const LOADS_ICON_NAMES[N_LOADS_ICONS] = {"House", "Caravan", "Boat"};

static void drawSettings(int page, const Config &e) {
  tft->fillScreen(C_BG);
  uiText("Settings", 10, 14, &FontValXS, C_TEXT);
  uiText(cfgCardPresent(cfgSource) ? "saved to CONFIG.TXT + memory" : "no SD card - saved in memory", 312, 14,
         &FontSmall, C_MUTED, 2);
  if (page == 0) {
    rowValue(0, "Shunt MAC", e.mac, &FontValXS);
    char k[24]; snprintf(k, sizeof(k), "%.6s...%.6s", e.key, e.key + 26);
    rowValue(1, "Key", k, &FontValXS);
    rowToggle(2, "Rotation", "Normal", "Flipped", e.rotation == 3);
    rowToggle(3, "Demo data", "Off", "On", e.demo);
  } else if (page == 1) {
    rowToggle(0, "Invert colours", "Off", "On", e.invert);
    rowStepper(1, "No signal after", e.staleAfterS, "s");
    rowStepper(2, "Amber below", e.socAmber, "%");
    rowStepper(3, "Red below", e.socRed, "%");
  } else if (page == 3) {
    for (int i = 0; i < CHARGER_SLOTS; i++) {
      char lbl[20];
      snprintf(lbl, sizeof(lbl), "Charger %d MAC", i + 1);
      rowValue(i * 2, lbl, e.chMac[i][0] ? e.chMac[i] : "Not used", e.chMac[i][0] ? &FontValXS : &FontLabel);
      snprintf(lbl, sizeof(lbl), "Charger %d key", i + 1);
      char k[24];
      if (e.chKey[i][0]) snprintf(k, sizeof(k), "%.6s...%.6s", e.chKey[i], e.chKey[i] + 26); else strcpy(k, "-");
      rowValue(i * 2 + 1, lbl, k, &FontValXS);
    }
  } else if (page == 4) {
    rowFrame(0, "Other charging");
    Btn m = {186, (int16_t)(rowY(0) + 5), 36, 28}, p = {276, (int16_t)(rowY(0) + 5), 36, 28};
    drawBtn(m, "<", C_BG, C_TEXT, &FontValS);
    drawBtn(p, ">", C_BG, C_TEXT, &FontValS);
    uiText(SOURCE_NAMES[e.otherSource < N_SOURCES ? e.otherSource : 0], 249, rowY(0) + 19, &FontSmall, C_TEXT, 1);
    rowFrame(1, "Loads icon");
    Btn m2 = {186, (int16_t)(rowY(1) + 5), 36, 28}, p2 = {276, (int16_t)(rowY(1) + 5), 36, 28};
    drawBtn(m2, "<", C_BG, C_TEXT, &FontValS);
    drawBtn(p2, ">", C_BG, C_TEXT, &FontValS);
    uiText(LOADS_ICON_NAMES[e.loadsIcon < N_LOADS_ICONS ? e.loadsIcon : 0], 249, rowY(1) + 19, &FontSmall, C_TEXT, 1);
    static const char *const HELP[4] = {
      "Extra chargers (page 4): Victron Blue Smart IP22,",
      "SmartSolar MPPT or Orion XS with Instant readout.",
      "To remove one: tap its MAC, Clear, then OK.",
      "Other charging: what they don't account for."};
    for (int i = 0; i < 4; i++) uiText(HELP[i], 10, rowY(2) + 10 + i * 17, &FontSmall, C_MUTED);
  } else {
    rowValue(0, "Touch", "Recalibrate  >");
    rowValue(1, "Screen chip", lcdChip == 8230 ? (lcdDetected ? "UC8230 (detected)" : "UC8230")
                                               : (lcdDetected ? "ILI9341 (detected)" : "ILI9341"));
    rowValue(2, "Touch pins", "");
    char tp[24];
    snprintf(tp, sizeof(tp), "D%d/A%d  D%d/A%d", touchHW.dA, touchHW.aA - A0, touchHW.dB, touchHW.aB - A0);
    uiText(tp, 302, rowY(2) + 19, &FontLabel, C_TEXT, 2);
    // Screen timeout: stepper through the preset list
    rowFrame(3, "Screen off after");
    Btn m = {186, (int16_t)(rowY(3) + 5), 36, 28}, p = {276, (int16_t)(rowY(3) + 5), 36, 28};
    drawBtn(m, "-", C_BG, C_TEXT, &FontValS);
    drawBtn(p, "+", C_BG, C_TEXT, &FontValS);
    char so[12];
    if (!e.screenOffS) strcpy(so, "Never");
    else if (e.screenOffS < 60) snprintf(so, sizeof(so), "%us", e.screenOffS);
    else snprintf(so, sizeof(so), "%um", e.screenOffS / 60);
    uiText(so, 249, rowY(3) + 19, e.screenOffS ? &FontValXS : &FontLabel, C_TEXT, 1);
  }
  drawBtn(B_CANCEL, "Cancel", RGB565(60, 66, 78), C_TEXT);
  drawBtn(B_PREV, "<", page > 0 ? C_PANEL : C_BG, page > 0 ? C_TEXT : C_PANEL, &FontValS);
  drawBtn(B_NEXT, ">", page < PAGES - 1 ? C_PANEL : C_BG, page < PAGES - 1 ? C_TEXT : C_PANEL, &FontValS);
  char pg[8]; snprintf(pg, sizeof(pg), "%d/%d", page + 1, PAGES);
  uiText(pg, 160, 218, &FontLabel, C_MUTED, 1);
  drawBtn(B_SAVE, "Save", C_GREEN, C_BG, &FontValXS);
}

// Returns when the user cancels (or leaves it alone for 90 s). Save restarts the board.
static void runSettings() {
  Config e = cfg;
  int page = 0;
  bool redraw = true;
  uint32_t lastAct = millis();
  while (true) {
    // Redrawn after every change, including coming back from the keypad or calibration, which
    // can take well over 90 s: count that as activity, or the page would close without saving.
    if (redraw) { drawSettings(page, e); redraw = false; lastAct = millis(); }
    int x, y;
    if (!waitTap(x, y, 500)) { if (millis() - lastAct > 90000) return; continue; }
    lastAct = millis();

    if (hit(B_CANCEL, x, y)) return;
    if (hit(B_PREV, x, y)) { if (page > 0) { page--; redraw = true; } continue; }
    if (hit(B_NEXT, x, y)) { if (page < PAGES - 1) { page++; redraw = true; } continue; }
    if (hit(B_SAVE, x, y)) {
      e.touchCalOk = cfg.touchCalOk; e.tRot = cfg.tRot; e.tSwap = cfg.tSwap;
      e.tx0 = cfg.tx0; e.tx1 = cfg.tx1; e.ty0 = cfg.ty0; e.ty1 = cfg.ty1; e.calChip = cfg.calChip;
      int saved = saveConfig(e);
      applySettings(e);
      if (saved & SAVED_SD) uiMessage("Saved", nullptr, C_GREEN);
      else if (saved) uiMessage("Saved", "in the display's memory (no SD card)", C_GREEN);
      else uiMessage("Couldn't save", "using these settings until power-off", C_AMBER);
      delay((saved & SAVED_SD) ? 700 : 1800);
      return;
    }
    if (y < rowY(0) || y >= rowY(4)) continue;
    int r = (y - rowY(0)) / 42;
    int side = rowSide(x), step = stepSide(x);

    if (page == 0) {
      if (r == 0) {
        char hex[13]; cfgHex(e.mac, hex, 12);
        if (hexEntry("Shunt MAC address", 12, hex)) cfgFormatMac(hex, e.mac);
        redraw = true;
      } else if (r == 1) {
        char hex[33]; strcpy(hex, e.key);
        if (hexEntry("Encryption key", 32, hex)) strcpy(e.key, hex);
        redraw = true;
      } else if (r == 2 && side) { e.rotation = side < 0 ? 1 : 3; redraw = true; }
      else if (r == 3 && side) { e.demo = side > 0; redraw = true; }
    } else if (page == 1) {
      if (r == 0 && side) { e.invert = side > 0; redraw = true; }
      else if (r == 1 && step) { e.staleAfterS = constrain((int)e.staleAfterS + step * 5, 5, 600); redraw = true; }
      else if (r == 2 && step) { e.socAmber = constrain((int)e.socAmber + step * 5, 0, 100); redraw = true; }
      else if (r == 3 && step) { e.socRed = constrain((int)e.socRed + step * 5, 0, 100); redraw = true; }
    } else if (page == 3) {
      int i = r / 2;
      if (r % 2 == 0) {
        char hex[13] = "";
        if (e.chMac[i][0]) cfgHex(e.chMac[i], hex, 12);
        char title[24]; snprintf(title, sizeof(title), "Charger %d MAC address", i + 1);
        if (hexEntry(title, 12, hex, true)) {
          if (hex[0]) cfgFormatMac(hex, e.chMac[i]);
          else { e.chMac[i][0] = 0; e.chKey[i][0] = 0; }       // cleared: the charger is removed
        }
      } else {
        char hex[33]; strcpy(hex, e.chKey[i]);
        char title[24]; snprintf(title, sizeof(title), "Charger %d key", i + 1);
        if (hexEntry(title, 32, hex, true)) strcpy(e.chKey[i], hex);
      }
      redraw = true;
    } else if (page == 4) {
      if (r == 0 && step) { e.otherSource = (e.otherSource + N_SOURCES + step) % N_SOURCES; redraw = true; }
      else if (r == 1 && step) { e.loadsIcon = (e.loadsIcon + N_LOADS_ICONS + step) % N_LOADS_ICONS; redraw = true; }
    } else {
      if (r == 0) { runCalibration(); redraw = true; }
      else if (r == 3 && step) {
        int i = constrain(screenOffIndex(e.screenOffS) + step, 0, N_SCREEN_OFF - 1);
        e.screenOffS = SCREEN_OFF_STEPS[i];
        redraw = true;
      }
    }
  }
}
