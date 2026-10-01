// The dashboard on the XC4630's 320x240 screen, in the same design as the Raspberry Pi and
// Android versions (and the AlphaESS display): a live energy-flow picture (the charger, the
// battery and the loads around a hub, with dots running along the lines the way the energy
// flows), a state-of-charge card and a card of the shunt's readings. Drawn for a small screen
// and a slow bus: the lines run straight, the dots only redraw their own line, and text
// changes through the off-screen canvas so it never flickers.
//
// Nodes sit at up to four places around the hub: a charge source at the top, an extra Victron
// charger on the left (when one is set up), the loads on the right and the battery at the
// bottom. What each shows is worked out in buildState() (ShuntDisplayR4.ino).
//
// Uses: dashOut (the screen), cv (the canvas, CW x CH), the fonts and colors.h.
#pragma once
#include "colors.h"

// ------------------------------------------------------------ what to show
enum { P_TOP, P_LEFT, P_RIGHT, P_BOTTOM, NPLACES };        // where a node sits
static const uint16_t NODE_COLOR[NPLACES] = {C_CHARGER, C_ACCENT, C_LOADS, C_BATTERY};
enum { I_VOLT, I_AMP, I_POWER, I_CONSUMED, I_STARTER, I_MIDPOINT, I_TEMP, I_SIGNAL,
       I_PLUG, I_SUN, I_CAR, I_BOLT, I_HOUSE, I_BATTERY, I_CARAVAN, I_BOAT };  // readings' icons, then the nodes'

struct DashState {
  char title[12] = "SmartShunt";
  char soc[8] = "--", time[12] = "--", timeLabel[12] = "";
  char status[12] = "", detail[20] = "";
  uint16_t statusColor = C_AMBER, socColor = C_MUTED;
  float bar = -1;                    // SOC for the bar, < 0 = empty
  float level = -1;                  // battery icon fill
  bool stale = true;
  // the nodes, by place
  bool has[NPLACES] = {true, false, true, true};
  uint8_t icon[NPLACES] = {I_PLUG, I_PLUG, I_HOUSE, I_BATTERY};
  float flow[NPLACES] = {0, 0, 0, 0};                     // watts, + toward the hub
  char value[NPLACES][12] = {"--", "", "--", "--"};
  char label[NPLACES][14] = {"Charger", "", "Loads", "Battery"};
  char extra[NPLACES][14] = {"", "", "", ""};
  uint16_t extraColor[NPLACES] = {C_MUTED, C_MUTED, C_MUTED, C_MUTED};
  char read[6][12] = {"--", "--", "--", "--", "--", "--"};
  uint16_t readColor[6] = {C_MUTED, C_MUTED, C_MUTED, C_MUTED, C_MUTED, C_MUTED};
  uint8_t auxMode = 3;               // 0 starter, 1 midpoint, 2/3 temperature
};

// ------------------------------------------------------------ layout (landscape 320x240)
// Header y0-26 | flow card 4,28 168x208 | charge card 176,28 140x66 | readings card 176,98 140x138
static const int FLOW_X = 4, FLOW_Y = 28, FLOW_W = 168, FLOW_H = 208;
static const int BATT_X = 176, BATT_Y = 28, BATT_W = 140, BATT_H = 66;
static const int READ_X = 176, READ_Y = 98, READ_W = 140, READ_H = 138;
static const int NODE_R = 17, HUB_R = 7;
static const int HUB_X = FLOW_X + FLOW_W / 2, HUB_Y = FLOW_Y + FLOW_H / 2;
// node centres, P_ order
static const int NODE_X[NPLACES] = {HUB_X, FLOW_X + 6 + NODE_R, FLOW_X + FLOW_W - 6 - NODE_R, HUB_X};
static const int NODE_Y[NPLACES] = {FLOW_Y + 6 + NODE_R, HUB_Y, HUB_Y, FLOW_Y + FLOW_H - 6 - NODE_R};
static const int READ_ROW0 = READ_Y + 22, READ_ROW_H = 19;
static const int READ_VAL_X = READ_X + 78, READ_VAL_W = 56;

// ------------------------------------------------------------ text fields
struct Field {
  int16_t x, y, w, h;
  uint16_t bg;
  char last[20];
  uint16_t lastColor;
};
// Each node has a value, a label and an extra line: F_NODE + place * 3 + 0/1/2
enum { F_STATUS, F_TITLE, F_NODE, F_SOC = F_NODE + NPLACES * 3, F_TLBL, F_TIME, F_AUXLBL,
       F_R0, F_R1, F_R2, F_R3, F_R4, F_R5, NFIELDS };
static const int TOP_TX = HUB_X + NODE_R + 5, TOP_TW = FLOW_X + FLOW_W - 4 - TOP_TX;   // right of the top node
static const int BOT_TX = FLOW_X + 4, BOT_TW = HUB_X - NODE_R - 5 - BOT_TX;           // left of the bottom node
static const int LEFT_TW = HUB_X - NODE_R - 3 - (FLOW_X + 2);                         // above the left node
static const int RIGHT_TX = HUB_X + 6, RIGHT_TW = FLOW_X + FLOW_W - 4 - RIGHT_TX;     // under the right node
Field fields[NFIELDS] = {
  {112,   4, 170, 20, C_BG},                                   // status pill
  {  4,   4, 106, 22, C_BG},                                   // title: SmartShunt / BMV-712
  {TOP_TX, 36, TOP_TW, 16, C_PANEL}, {TOP_TX, 55, TOP_TW, 13, C_PANEL}, {TOP_TX, 68, TOP_TW, 13, C_PANEL},
  {FLOW_X + 2, 70, LEFT_TW, 16, C_PANEL}, {FLOW_X + 2, 87, LEFT_TW, 13, C_PANEL}, {FLOW_X + 2, 100, LEFT_TW, 13, C_PANEL},
  {RIGHT_TX, HUB_Y + NODE_R + 5, RIGHT_TW, 16, C_PANEL}, {RIGHT_TX, HUB_Y + NODE_R + 22, RIGHT_TW, 13, C_PANEL},
  {RIGHT_TX, HUB_Y + NODE_R + 35, RIGHT_TW, 13, C_PANEL},
  {BOT_TX, 184, BOT_TW, 16, C_PANEL}, {BOT_TX, 201, BOT_TW, 13, C_PANEL}, {BOT_TX, 215, BOT_TW, 13, C_PANEL},
  {BATT_X + 8, BATT_Y + 8, 62, 28, C_PANEL},                   // SOC %
  {BATT_X + 74, BATT_Y + 9, 60, 12, C_PANEL},                  // Time left / Battery
  {BATT_X + 74, BATT_Y + 22, 60, 15, C_PANEL},                 // time / Charging / Full
  {READ_X + 22, 0, 54, 15, C_PANEL},                           // aux label: Starter / Midpoint / Temp
  {READ_VAL_X, 0, READ_VAL_W, 15, C_PANEL}, {READ_VAL_X, 0, READ_VAL_W, 15, C_PANEL},    // readings'
  {READ_VAL_X, 0, READ_VAL_W, 15, C_PANEL}, {READ_VAL_X, 0, READ_VAL_W, 15, C_PANEL},    // values
  {READ_VAL_X, 0, READ_VAL_W, 15, C_PANEL}, {READ_VAL_X, 0, READ_VAL_W, 15, C_PANEL},
};

static void dashLayoutFields() {
  for (int i = 0; i < 6; i++) fields[F_R0 + i].y = READ_ROW0 + i * READ_ROW_H + 2;
  fields[F_AUXLBL].y = READ_ROW0 + 4 * READ_ROW_H + 2;
}

// Copies the canvas's top-left w x h to the screen.
static void blitField(const Field &f) {
  uint16_t *fb = cv->getFramebuffer();
  for (int row = 0; row < f.h; row++) dashOut->draw16bitRGBBitmap(f.x, f.y + row, fb + row * CW, f.w, 1);
}

// Draws text into a field. align: 0 left, 1 centre, 2 right. Shrinks the font if too wide.
// baseline >= 0 puts the text on that baseline (from the field's top) instead of centring its ink.
void drawField(int id, const char *text, uint16_t color, const GFXfont *font, int align = 0,
               const GFXfont *smaller = nullptr, const GFXfont *smallest = nullptr, int baseline = -1) {
  Field &f = fields[id];
  if (strcmp(f.last, text) == 0 && f.lastColor == color) return;  // unchanged
  strncpy(f.last, text, sizeof(f.last) - 1);
  f.lastColor = color;
  cv->fillRect(0, 0, f.w, f.h, f.bg);
  const GFXfont *fonts[3] = {font, smaller, smallest};
  int16_t bx, by; uint16_t bw, bh;
  for (int i = 0; i < 3 && fonts[i]; i++) {
    cv->setFont(fonts[i]);
    cv->getTextBounds(text, 0, 0, &bx, &by, &bw, &bh);
    if (bw <= f.w) break;
  }
  int x = align == 1 ? (f.w - (int)bw) / 2 - bx : align == 2 ? f.w - (int)bw - bx : -bx;
  int y = baseline >= 0 ? baseline : (f.h - (int)bh) / 2 - by;
  cv->setTextColor(color);
  cv->setCursor(x, y);
  cv->print(text);
  blitField(f);
}

// The status pill: a coloured dot, the status word and a detail, right-aligned in its field.
void drawStatusField(const char *word, uint16_t color, const char *detail) {
  Field &f = fields[F_STATUS];
  char key[20];
  snprintf(key, sizeof(key), "%.9s|%.9s", word, detail);
  if (strcmp(f.last, key) == 0 && f.lastColor == color) return;
  strncpy(f.last, key, sizeof(f.last) - 1);
  f.lastColor = color;
  int16_t bx, by; uint16_t ww, wh, dw = 0, dh;
  cv->setFont(&FontLabel);
  cv->getTextBounds(word, 0, 0, &bx, &by, &ww, &wh);
  if (*detail) { cv->setFont(&FontSmall); cv->getTextBounds(detail, 0, 0, &bx, &by, &dw, &dh); }
  int pw = 8 + 6 + 6 + ww + (*detail ? 7 + dw : 0) + 9;
  if (pw > f.w) pw = f.w;
  int px = f.w - pw;
  cv->fillRect(0, 0, f.w, f.h, f.bg);
  cv->fillRoundRect(px, 0, pw, f.h, f.h / 2, C_PANEL);
  int x = px + 9;
  cv->fillCircle(x + 3, f.h / 2, 3, color);
  x += 12;
  cv->setFont(&FontLabel);
  cv->setTextColor(color);
  cv->setCursor(x, 15);
  cv->print(word);
  if (*detail) {
    cv->setFont(&FontSmall);
    cv->setTextColor(C_MUTED);
    cv->setCursor(x + ww + 7, 14);
    cv->print(detail);
  }
  blitField(f);
}

// ------------------------------------------------------------ shapes and icons
static void thickLine(Arduino_GFX *g, int x0, int y0, int x1, int y1, int w, uint16_t c) {
  if (w <= 1) { g->drawLine(x0, y0, x1, y1, c); return; }
  for (int dx = 0; dx < w; dx++)
    for (int dy = 0; dy < w; dy++) g->drawLine(x0 + dx - w / 2, y0 + dy - w / 2, x1 + dx - w / 2, y1 + dy - w / 2, c);
}

// A lightning bolt about h pixels tall.
static void dashBolt(Arduino_GFX *g, int cx, int cy, int h, uint16_t c) {
  float s = h / 10.0f;
  g->fillTriangle(cx + 1 * s, cy - 5 * s, cx - 3 * s, cy + 1 * s, cx + 1 * s, cy + 1 * s, c);
  g->fillTriangle(cx - 1 * s, cy + 5 * s, cx + 3 * s, cy - 1 * s, cx - 1 * s, cy - 1 * s, c);
}

// Battery outline `s` tall, with a fill `level` (0-100, < 0 none). Returns nothing.
static void dashBattery(Arduino_GFX *g, int cx, int cy, int s, uint16_t c, uint16_t bg, int level, bool split) {
  int w = s >= 16 ? 2 : 1;
  int bw = s * 0.5f, bh = s * 0.78f, x = cx - bw / 2, y = cy - bh / 2 + s * 0.06f;
  g->fillRect(cx - s * 0.1f, y - s * 0.1f, s * 0.2f + 1, s * 0.1f + 1, c);
  g->fillRoundRect(x, y, bw, bh, 2, c);
  g->fillRect(x + w, y + w, bw - 2 * w, bh - 2 * w, bg);
  if (split) g->drawFastHLine(x + 2 * w, y + bh / 2, bw - 4 * w, c);
  else if (level > 0) {
    int fh = (bh - 4 * w) * (level > 100 ? 100 : level) / 100;
    if (fh > 0) g->fillRect(x + 2 * w, y + bh - 2 * w - fh, bw - 4 * w, fh, c);
  }
}

// A small - badge (consumed).
static void dashBadge(Arduino_GFX *g, int cx, int cy, int r, uint16_t c, uint16_t bg) {
  g->fillCircle(cx, cy, r + 1, bg);
  g->fillCircle(cx, cy, r, c);
  g->drawFastHLine(cx - r + 2, cy, 2 * r - 3, bg);
}

// Icons `s` pixels across, centred on cx, cy: the flow nodes and the readings.
static void dashIcon(Arduino_GFX *g, int kind, int cx, int cy, int s, uint16_t c, uint16_t bg, int level = 50) {
  int w = s >= 16 ? 2 : 1;
  if (kind == I_PLUG) {                                      // a mains plug
    thickLine(g, cx - s * 0.15f, cy - s * 0.46f, cx - s * 0.15f, cy - s * 0.24f, w, c);
    thickLine(g, cx + s * 0.15f, cy - s * 0.46f, cx + s * 0.15f, cy - s * 0.24f, w, c);
    g->fillRoundRect(cx - s * 0.3f, cy - s * 0.26f, s * 0.6f + 1, s * 0.36f, 2, c);
    g->fillRect(cx - s * 0.08f, cy + s * 0.08f, s * 0.16f + 1, s * 0.16f, c);
    thickLine(g, cx, cy + s * 0.2f, cx, cy + s * 0.46f, w, c);
  } else if (kind == I_SUN) {                                // a sun
    g->fillCircle(cx, cy, s * 0.2f, c);
    for (int i = 0; i < 8; i++) {
      float a = i * 3.14159265f / 4, co = cosf(a), si = sinf(a);
      thickLine(g, cx + co * s * 0.34f, cy + si * s * 0.34f, cx + co * s * 0.47f, cy + si * s * 0.47f, w, c);
    }
  } else if (kind == I_CAR) {                                // a car: DC-DC charger or alternator
    g->fillTriangle(cx - s * 0.3f, cy - s * 0.04f, cx - s * 0.18f, cy - s * 0.34f, cx - s * 0.18f, cy - s * 0.04f, c);
    g->fillTriangle(cx + s * 0.32f, cy - s * 0.04f, cx + s * 0.18f, cy - s * 0.34f, cx + s * 0.18f, cy - s * 0.04f, c);
    g->fillRect(cx - s * 0.18f, cy - s * 0.34f, s * 0.36f + 1, s * 0.3f + 1, c);
    g->fillRect(cx - s * 0.13f, cy - s * 0.27f, s * 0.11f + 1, s * 0.17f, bg);   // windows
    g->fillRect(cx + s * 0.03f, cy - s * 0.27f, s * 0.11f + 1, s * 0.17f, bg);
    g->fillRoundRect(cx - s * 0.47f, cy - s * 0.08f, s * 0.94f + 1, s * 0.3f, 2, c);
    for (int sx = -1; sx <= 1; sx += 2) {
      g->fillCircle(cx + sx * s * 0.25f, cy + s * 0.24f, s * 0.15f + 1, bg);
      g->fillCircle(cx + sx * s * 0.25f, cy + s * 0.24f, s * 0.11f + 1, c);
    }
  } else if (kind == I_BOLT) {                               // a bolt: charging from somewhere else
    dashBolt(g, cx, cy, s, c);
  } else if (kind == I_CARAVAN) {                            // a caravan: body, window, wheel, drawbar
    int l = cx - s * 0.5f, r = cx + s * 0.3f, t = cy - s * 0.36f, b = cy + s * 0.2f;
    g->fillRoundRect(l, t, r - l + 1, b - t + 1, 2, c);
    g->fillRect(l + w, t + w, r - l + 1 - 2 * w, b - t + 1 - 2 * w, bg);
    g->fillRect(l + w + 2, t + w + 2, s * 0.3f, s * 0.14f + 1, c);                // window
    g->fillRect(r - w - 3, t + w + 2, 2, b - t - 2 * w - 2, c);                   // door
    thickLine(g, r, b - 1, cx + s * 0.5f, b - 1, w, c);                          // drawbar
    int wx = cx - s * 0.1f, wy = b + 1;
    g->fillCircle(wx, wy, 4, bg);
    g->fillCircle(wx, wy, 3, c);
    g->drawPixel(wx, wy, bg);
  } else if (kind == I_BOAT) {                               // a sailing boat: hull and two sails
    int hl = cx - s * 0.48f, hr = cx + s * 0.48f, ht = cy + s * 0.14f, hb = cy + s * 0.4f;
    g->fillRect(cx - s * 0.32f, ht, s * 0.64f + 1, hb - ht + 1, c);
    g->fillTriangle(hl, ht, cx - s * 0.32f, ht, cx - s * 0.32f, hb, c);
    g->fillTriangle(hr, ht, cx + s * 0.32f, ht, cx + s * 0.32f, hb, c);
    g->drawFastVLine(cx - 1, cy - s * 0.48f, s * 0.62f, c);                      // mast
    g->fillTriangle(cx - 2, cy - s * 0.42f, cx - 2, cy + s * 0.06f, cx - s * 0.4f, cy + s * 0.06f, c);
    g->fillTriangle(cx + 1, cy - s * 0.34f, cx + 1, cy + s * 0.06f, cx + s * 0.34f, cy + s * 0.06f, c);
  } else if (kind == I_HOUSE) {                              // a house
    int l = cx - s * 0.34f, r = cx + s * 0.34f, t = cy - s * 0.46f, b = cy + s * 0.4f, eave = cy - s * 0.06f;
    thickLine(g, cx - s * 0.48f, eave + s * 0.04f, cx, t, w, c);
    thickLine(g, cx, t, cx + s * 0.48f, eave + s * 0.04f, w, c);
    thickLine(g, l, eave, l, b, w, c);
    thickLine(g, r, eave, r, b, w, c);
    thickLine(g, l, b, r, b, w, c);
    g->fillRect(cx - s * 0.09f, cy + s * 0.1f, s * 0.2f + 1, b - (cy + s * 0.1f), c);
  } else if (kind == I_BATTERY) {
    dashBattery(g, cx, cy, s, c, bg, level, false);
  } else if (kind == I_VOLT) {
    dashBolt(g, cx, cy, s, c);
  } else if (kind == I_AMP) {                                // arrows both ways
    int y1 = cy - s / 5, y2 = cy + s / 5, l = cx - s / 2 + 1, r = cx + s / 2 - 1;
    g->drawFastHLine(l, y1, r - l, c);
    g->fillTriangle(r, y1, r - 3, y1 - 2, r - 3, y1 + 2, c);
    g->drawFastHLine(l, y2, r - l, c);
    g->fillTriangle(l, y2, l + 3, y2 - 2, l + 3, y2 + 2, c);
  } else if (kind == I_POWER) {                              // a bolt in a ring
    g->drawCircle(cx, cy, s / 2, c);
    dashBolt(g, cx, cy, s * 0.6f, c);
  } else if (kind == I_CONSUMED) {                           // a battery with a minus badge
    dashBattery(g, cx - 1, cy, s, c, bg, 50, false);
    dashBadge(g, cx + s * 0.3f, cy + s * 0.3f, 3, c, bg);
  } else if (kind == I_STARTER) {                            // a car battery: wide, two terminals
    int bw = s * 0.84f, bh = s * 0.54f, x = cx - bw / 2, y = cy - bh / 2 + 1;
    g->fillRect(x + 2, y - 2, 3, 2, c);
    g->fillRect(x + bw - 5, y - 2, 3, 2, c);
    g->drawRect(x, y, bw, bh, c);
  } else if (kind == I_MIDPOINT) {
    dashBattery(g, cx, cy, s, c, bg, -1, true);
  } else if (kind == I_TEMP) {                               // a thermometer
    g->fillCircle(cx, cy + s * 0.28f, s / 5, c);
    g->drawRoundRect(cx - 2, cy - s / 2, 5, s * 0.72f, 2, c);
    g->drawFastVLine(cx, cy - s / 2 + 3, s * 0.6f, c);
  } else {                                                   // signal: four bars
    for (int i = 0; i < 4; i++) {
      int h = 3 + i * 3;
      g->fillRect(cx - s / 2 + 1 + i * 3, cy + s / 2 - h, 2, h, c);
    }
  }
}

static void dashCog(Arduino_GFX *g, int cx, int cy, uint16_t col, uint16_t bg) {
  for (int i = 0; i < 8; i++) {
    float a = i * 3.14159265f / 4;
    g->fillCircle(cx + cosf(a) * 8.5f, cy + sinf(a) * 8.5f, 2, col);
  }
  g->fillCircle(cx, cy, 7, col);
  g->fillCircle(cx, cy, 3, bg);
}

static void staticText(const char *text, int x, int baseline, const GFXfont *font, uint16_t color, int align = 0) {
  int16_t bx, by; uint16_t bw, bh;
  dashOut->setFont(font);
  dashOut->getTextBounds(text, 0, 0, &bx, &by, &bw, &bh);
  dashOut->setTextColor(color);
  dashOut->setCursor(align == 2 ? x - (int)bw - bx : align == 1 ? x - (int)bw / 2 - bx : x, baseline);
  dashOut->print(text);
}

// ------------------------------------------------------------ energy flow
// Each line runs from its node's edge (0) to the hub's edge (len), straight across or down.
struct FlowLine { int x0, y0, dx, dy, len; };
static FlowLine flowLine(int k) {
  int nx = NODE_X[k], ny = NODE_Y[k];
  int dx = (HUB_X > nx) - (HUB_X < nx), dy = (HUB_Y > ny) - (HUB_Y < ny);
  int gap = NODE_R + 4;
  int dist = abs(HUB_X - nx) + abs(HUB_Y - ny);
  return {nx + dx * gap, ny + dy * gap, dx, dy, dist - gap - HUB_R - 4};
}

static bool lineActive[NPLACES] = {false, false, false, false};
static int8_t nodeDrawn[NPLACES] = {-1, -1, -1, -1};
static uint8_t nodeIcon[NPLACES] = {0, 0, 0, 0};
static bool placeShown[NPLACES] = {true, false, true, true};   // set by dashDrawStatic
static int lastLevel = -2;

static bool flowActive(const DashState &s, int k) {
  float p = s.flow[k];
  return !s.stale && s.has[k] && !isnan(p) && fabsf(p) > 3;
}

// Clears a line's strip and draws its track.
static void drawTrack(int k, bool active) {
  FlowLine l = flowLine(k);
  int x = l.x0 + (l.dx < 0 ? -l.len : 0), y = l.y0 + (l.dy < 0 ? -l.len : 0);
  int w = l.dx ? l.len + 1 : 7, h = l.dy ? l.len + 1 : 7;
  if (l.dx) y -= 3; else x -= 3;
  dashOut->fillRect(x, y, w, h, C_PANEL);
  uint16_t c = active ? mix565(NODE_COLOR[k], C_PANEL, 0.72f) : C_LINE;
  if (l.dx) dashOut->fillRect(x, y + 2, w, 3, c); else dashOut->fillRect(x + 2, y, 3, h, c);
}

static void drawNode(int k, int icon, bool active, int level) {
  int x = NODE_X[k], y = NODE_Y[k];
  uint16_t tint = mix565(NODE_COLOR[k], C_PANEL, 0.86f);
  uint16_t ring = active ? NODE_COLOR[k] : mix565(NODE_COLOR[k], C_PANEL, 0.55f);
  dashOut->fillCircle(x, y, NODE_R, tint);
  dashOut->drawCircle(x, y, NODE_R, ring);
  dashOut->drawCircle(x, y, NODE_R - 1, ring);
  dashIcon(dashOut, icon, x, y, 19, NODE_COLOR[k], tint, level);
}

// Moves the dots along every active line. Call often (every 40 ms or so).
void dashAnimate(const DashState &s, uint32_t ms) {
  int level = s.level < 0 ? -1 : (int)(s.level + 0.5f);
  for (int k = 0; k < NPLACES; k++) {
    if (!placeShown[k]) continue;
    bool on = flowActive(s, k);
    if (on != lineActive[k]) { lineActive[k] = on; drawTrack(k, on); }
    bool redrawNode = (int8_t)on != nodeDrawn[k] || s.icon[k] != nodeIcon[k]
                      || (k == P_BOTTOM && level / 10 != lastLevel / 10);
    if (redrawNode) {
      nodeDrawn[k] = on; nodeIcon[k] = s.icon[k];
      drawNode(k, s.icon[k], on, level);
      if (k == P_BOTTOM) lastLevel = level;
    }
    if (!on) continue;
    FlowLine l = flowLine(k);
    float kw = fabsf(s.flow[k]) / 1000;
    float speed = 22 + 18 * (kw > 3 ? 3 : kw);              // pixels a second
    const int gap = 12;
    int off = (int)(ms / 1000.0f * speed) % gap;
    drawTrack(k, true);
    bool forward = s.flow[k] > 0;                          // toward the hub
    for (int d = off; d <= l.len; d += gap) {
      int t = forward ? d : l.len - d;
      int edge = d < l.len - d ? d : l.len - d;
      dashOut->fillCircle(l.x0 + l.dx * t, l.y0 + l.dy * t, edge < 3 ? 1 : 2, NODE_COLOR[k]);
    }
  }
}

// ------------------------------------------------------------ static parts
static const char *READ_LABEL[6] = {"Voltage", "Current", "Power", "Consumed", "", "Signal"};
static const int READ_ICON[6] = {I_VOLT, I_AMP, I_POWER, I_CONSUMED, I_TEMP, I_SIGNAL};
static const uint16_t READ_ICON_COLOR[6] = {C_CHARGER, C_LOADS, C_ACCENT, C_BATTERY, C_ACCENT, C_LOADS};
static int8_t auxDrawn = -1;

// The aux row's icon and label: starter battery, midpoint or temperature.
static void drawAuxRow(uint8_t mode) {
  int top = READ_ROW0 + 4 * READ_ROW_H, mid = top + READ_ROW_H / 2;
  dashOut->fillRect(READ_X + 5, top + 1, 16, READ_ROW_H - 2, C_PANEL);
  int icon = mode == 0 ? I_STARTER : mode == 1 ? I_MIDPOINT : I_TEMP;
  uint16_t col = mode == 0 ? C_CHARGER : mode == 1 ? C_BATTERY : C_ACCENT;
  dashIcon(dashOut, icon, READ_X + 13, mid, 12, col, C_PANEL);
  drawField(F_AUXLBL, mode == 0 ? "Starter" : mode == 1 ? "Midpoint" : "Temp", C_MUTED, &FontSmall, 0, nullptr, nullptr, 11);
  auxDrawn = mode;
}

// `left`: an extra charger is set up, so there's a node on the left.
void dashDrawStatic(bool cog, bool left) {
  dashLayoutFields();
  dashOut->fillScreen(C_BG);
  if (cog) dashCog(dashOut, 304, 13, C_MUTED, C_BG);
  dashOut->fillRoundRect(FLOW_X, FLOW_Y, FLOW_W, FLOW_H, 8, C_PANEL);
  dashOut->fillRoundRect(BATT_X, BATT_Y, BATT_W, BATT_H, 8, C_PANEL);
  dashOut->fillRoundRect(READ_X, READ_Y, READ_W, READ_H, 8, C_PANEL);
  // flow: hub, lines and nodes (drawn idle; dashAnimate lights them up and draws the icons)
  for (int k = 0; k < NPLACES; k++) {
    placeShown[k] = k != P_LEFT || left;
    lineActive[k] = false; nodeDrawn[k] = -1;
    if (placeShown[k]) drawTrack(k, false);
  }
  lastLevel = -2;
  dashOut->fillCircle(HUB_X, HUB_Y, HUB_R + 1, C_LINE);
  dashOut->fillCircle(HUB_X, HUB_Y, HUB_R - 1, C_PANEL);
  dashBolt(dashOut, HUB_X, HUB_Y, 10, C_MUTED);
  // readings: title, row icons, labels and dividers
  staticText("Readings", READ_X + 8, READ_Y + 16, &FontLabel, C_TEXT);
  for (int i = 0; i < 6; i++) {
    int top = READ_ROW0 + i * READ_ROW_H, mid = top + READ_ROW_H / 2;
    if (i > 0 && i % 2 == 0) dashOut->drawFastHLine(READ_X + 8, top, READ_W - 16, C_LINE);
    if (i == 4) continue;                                   // the aux row changes with the shunt's setting
    dashIcon(dashOut, READ_ICON[i], READ_X + 13, mid, 12, READ_ICON_COLOR[i], C_PANEL);
    staticText(READ_LABEL[i], READ_X + 22, mid + 4, &FontSmall, C_MUTED);
  }
  for (int i = 0; i < NFIELDS; i++) { fields[i].last[0] = 1; fields[i].last[1] = 0; }
  auxDrawn = -1;
}

// ------------------------------------------------------------ changing parts
static int barLastPx = -1; static uint16_t barLastCol = 0;

void dashUpdate(const DashState &s) {
  uint16_t vcol = s.stale ? C_MUTED : C_TEXT;
  drawField(F_TITLE, s.title, C_TEXT, &FontValXS, 0, &FontLabel, nullptr, 15);
  drawStatusField(s.status, s.statusColor, s.detail);
  static const uint8_t ALIGN[NPLACES] = {0, 1, 2, 2};      // top: left of its field; left: centred; right, bottom: right
  for (int k = 0; k < NPLACES; k++) {
    if (!placeShown[k]) continue;
    int f = F_NODE + k * 3;
    uint16_t vc = !strcmp(s.value[k], "--") ? C_MUTED : vcol;
    drawField(f, s.value[k], vc, &FontValXS, ALIGN[k], &FontLabel, nullptr, 13);
    drawField(f + 1, s.label[k], C_MUTED, &FontSmall, ALIGN[k], nullptr, nullptr, 10);
    if (k != P_RIGHT)                                      // the loads have no third line
      drawField(f + 2, s.extra[k], s.extraColor[k], &FontSmall, ALIGN[k], nullptr, nullptr, 10);
  }
  drawField(F_SOC, s.soc, s.socColor, &FontVal, 0, &FontValS, &FontValXS, 22);
  drawField(F_TLBL, s.timeLabel, C_MUTED, &FontSmall, 0, nullptr, nullptr, 10);
  drawField(F_TIME, s.time, vcol, &FontLabel, 0, &FontSmall, nullptr, 12);
  uint8_t aux = s.auxMode > 2 ? 2 : s.auxMode;
  if ((int8_t)aux != auxDrawn) drawAuxRow(aux);
  for (int i = 0; i < 6; i++)
    drawField(F_R0 + i, s.read[i], s.readColor[i], &FontLabel, 2, &FontSmall, nullptr, 12);
  // SOC bar
  const int bx = BATT_X + 8, by = BATT_Y + BATT_H - 16, bw = BATT_W - 16, bh = 8;
  int px = s.bar < 0 ? 0 : (int)(bw * (s.bar > 100 ? 100 : s.bar) / 100.0f);
  if (px != barLastPx || s.socColor != barLastCol) {
    barLastPx = px; barLastCol = s.socColor;
    dashOut->fillRoundRect(bx, by, bw, bh, bh / 2, C_BG);
    if (px > 0) dashOut->fillRoundRect(bx, by, px < bh ? bh : px, bh, bh / 2, s.socColor);
  }
}

// Forget what's on screen (after the settings screens): everything is drawn again.
void dashInvalidate() { barLastPx = -1; lastLevel = -2; for (int k = 0; k < NPLACES; k++) nodeDrawn[k] = -1; auxDrawn = -1; }
