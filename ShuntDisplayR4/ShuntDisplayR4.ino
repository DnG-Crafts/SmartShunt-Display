// ============================================================================
//  Victron SmartShunt display — Arduino UNO R4 WiFi + Jaycar XC4630 2.8" TFT shield
//  Same look as the Raspberry Pi version, laid out for 320x240.
//
//  Libraries (Arduino IDE > Library Manager):
//    - ArduinoBLE
//    - GFX Library for Arduino   (by Moon On Our Nation, v1.4.6 or newer)
//    - SD                        (by Arduino; usually already installed)
//
//  All settings (shunt MAC & key, demo mode, rotation...) live in CONFIG.TXT on
//  the screen's SD card. Change them on the display itself (tap the cog in the
//  Status box) or edit the file on a computer.
//  Hold the screen while powering on to recalibrate the touch panel.
// ============================================================================

#include <ArduinoBLE.h>
#if defined(ARDUINO_UNOR4_WIFI)
#include <Modem.h>          // link to the R4 WiFi's radio chip (part of the R4 core, used by ArduinoBLE)
extern ModemClass modem;
#endif
#include <Arduino_GFX_Library.h>
#include "Arduino_R4PAR8.h"
#include "Arduino_UC8230.h"
#include "config.h"
#include "victron.h"
#include "fonts.h"

// ------------------------------------------------------------ display objects
Arduino_DataBus *bus = new Arduino_R4PAR8();
Arduino_TFT *tft = nullptr;  // created in setup() once the chip type is known

Arduino_GFX *dashOut = nullptr;   // what the dashboard draws on (the screen)

// One small off-screen buffer; every changing value is drawn into it and then
// copied to the screen in one go, so numbers update without flicker.
const int CW = 182, CH = 30;
Arduino_Canvas *cv = new Arduino_Canvas(CW, CH, nullptr);

// ------------------------------------------------------------ colours & fonts
#include "colors.h"

// ------------------------------------------------------------ state
ShuntReading reading;
uint32_t lastHeard = 0;      // millis() of last good packet (0 = never)
int lastRssi = 0;
uint32_t lastBadKey = 0;
uint8_t key[16];
bool keyOk = false;
// Extra Victron chargers: what was last heard from each
struct ChargerSlot {
  ChargerReading reading;
  uint32_t heard = 0, badKey = 0;   // millis(); 0 = never
  uint8_t key[16];
  bool keyOk = false;
} chargers[CHARGER_SLOTS];
Config cfg;
ConfigSource cfgSource;
int cfgBadLines = 0;
bool setupNeeded = false;
uint16_t lcdChip = 0;        // screen chip in use: 9341 or 8230
bool lcdDetected = false;    // true if it was identified (not the lcd_chip fallback)
bool screenDark = false;
uint32_t lastTouchAt = 0;
bool bleStarted = false, bleFailed = false;
uint32_t bleRetryAt = 0;
void applySettings(const Config &e);

#include "ui.h"          // touch, calibration and settings screens
#include "dashboard.h"   // the dashboard

DashState dash;          // what the dashboard shows (filled by buildState)
void buildState();

// ------------------------------------------------------------ helpers
uint16_t socColour(float soc) {
  if (isnan(soc)) return C_MUTED;
  return soc >= cfg.socAmber ? C_GREEN : soc >= cfg.socRed ? C_AMBER : C_RED;
}

void fmt(char *buf, size_t n, float v, int decimals, const char *unit, bool sign = false) {
  if (isnan(v)) { snprintf(buf, n, "--"); return; }
  char num[12];
  if (sign && v > 0) { num[0] = '+'; dtostrf(v, 0, decimals, num + 1); }
  else dtostrf(v, 0, decimals, num);
  snprintf(buf, n, "%s%s", num, unit);
}

// Watts without a sign: "456 W", "4.91 kW", "12.4 kW"
void fmtPower(char *buf, size_t n, float w) {
  if (isnan(w)) { snprintf(buf, n, "--"); return; }
  long a = (long)(fabsf(w) + 0.5f);
  if (a < 1000) snprintf(buf, n, "%ld W", a);
  else if (a < 9995) { long c = (a + 5) / 10; snprintf(buf, n, "%ld.%02ld kW", c / 100, c % 100); }
  else { long d = (a + 50) / 100; snprintf(buf, n, "%ld.%ld kW", d / 10, d % 10); }
}

// The shunt's alarm bits, by name
static const char *ALARM_NAMES[14] = {"Low voltage", "High voltage", "Low SOC", "Low starter V", "High starter V",
                                      "Low temp", "High temp", "Midpoint V", "Overload", "DC ripple",
                                      "Low AC out", "High AC out", "Short circuit", "BMS lockout"};

// ------------------------------------------------------------ BLE
void onDiscovered(BLEDevice dev) {
  String addr = dev.address();
  int slot = -1;
  for (int i = 0; i < CHARGER_SLOTS; i++) if (chargerUsed(cfg, i) && addr.equalsIgnoreCase(cfg.chMac[i])) slot = i;
  if (slot < 0 && !addr.equalsIgnoreCase(cfg.mac)) return;
  uint8_t md[40];
  int n = dev.manufacturerData(md, sizeof(md));
  if (n < 10 || md[0] != 0xE1 || md[1] != 0x02) return;  // Victron company ID 0x02E1
  if (slot >= 0) {                                       // one of the extra chargers
    ChargerSlot &c = chargers[slot];
    ChargerReading cr;
    VictronResult res = c.keyOk ? victronDecodeCharger(md + 2, n - 2, c.key, cr) : VIC_BAD_KEY;
    if (res == VIC_OK) { c.reading = cr; c.heard = millis() ? millis() : 1; }
    else if (res == VIC_BAD_KEY) c.badKey = millis() ? millis() : 1;
    return;
  }
  ShuntReading r;
  VictronResult res = victronDecode(md + 2, n - 2, key, r);
  if (res == VIC_OK) {
    reading = r;
    lastHeard = millis() ? millis() : 1;
    lastRssi = dev.rssi();
  } else if (res == VIC_BAD_KEY) {
    lastBadKey = millis();
  }
}

// On the R4 WiFi, Bluetooth runs on a separate radio chip. A restart of the main chip only
// (reset button, or a new upload) can leave the radio's Bluetooth running, and it then
// refuses to start again. If that happens, restart the radio chip and try once more.
bool radioRestarted = false;
void restartRadio() {
#if defined(ARDUINO_UNOR4_WIFI)
  Serial.println("Restarting the radio chip...");
  modem.begin();
  std::string res;
  modem.timeout(300);                       // it restarts without answering
  modem.write(std::string(PROMPT(_RESET)), res, CMD(_RESET));
  modem.timeout(MODEM_TIMEOUT);
#endif
}

void startScan();
bool bleWanted() { return !cfg.demo && !setupNeeded; }

// Start Bluetooth. If it fails, keep running (touch still works) and retry later.
void startBLE() {
  if (BLE.begin()) {
    BLE.setEventHandler(BLEDiscovered, onDiscovered);
    startScan();
    bleStarted = true; bleFailed = false;
    Serial.println("Bluetooth started");
    return;
  }
  bleFailed = true;
  if (!radioRestarted) {
    restartRadio();
    radioRestarted = true;
    bleRetryAt = millis() + 4000;           // give it time to boot
  } else {
    bleRetryAt = millis() + 15000;
    Serial.println("Bluetooth failed to start - retrying in 15 s");
  }
}

void startScan() {
  BLE.stopScan();
  BLE.scan(true);  // true = report every advertisement, not just the first
}

// ------------------------------------------------------------ demo data
void demoTick() {
  float t = millis() / 1000.0f;
  float cur = -8.5f + 14 * sinf(t / 20);
  reading.valid = true;
  reading.current = cur;
  reading.voltage = 13.1f + 0.02f * cur;
  reading.soc = 78.4f - fmodf(t / 60, 20);
  reading.consumedAh = -21.6f;
  reading.remainingMins = cur > 0 ? -1 : 1234;
  reading.alarm = 0;
  reading.auxMode = 0;
  reading.aux = 12.6f;
  lastHeard = millis() ? millis() : 1;
  lastRssi = -67;
  // configured chargers: a mains charger that comes and goes, a solar charger with the sun
  for (int i = 0; i < CHARGER_SLOTS; i++) {
    if (!chargerUsed(cfg, i)) continue;
    ChargerSlot &c = chargers[i];
    uint8_t kind = c.reading.valid ? c.reading.kind : CHG_MAINS;
    bool mains = kind == CHG_MAINS;
    float watts = (mains ? 400 : 180) * sinf(t / (mains ? 35 : 50));
    if (watts < 0) watts = 0;
    ChargerReading cr;
    cr.valid = true; cr.kind = kind; cr.error = 0;
    cr.voltage = reading.voltage; cr.current = watts / cr.voltage; cr.power = watts;
    cr.state = watts <= 0 ? 0 : watts < 150 ? 5 : 3;
    c.reading = cr;
    c.heard = lastHeard;
    reading.current += cr.current;
  }
}

// The charger slots' keys, from the settings (and forget old readings if a slot changed).
void setupChargers(const Config *old) {
  for (int i = 0; i < CHARGER_SLOTS; i++) {
    ChargerSlot &c = chargers[i];
    if (!old || strcmp(old->chMac[i], cfg.chMac[i]) || strcmp(old->chKey[i], cfg.chKey[i]) || old->demo != cfg.demo)
      c = ChargerSlot();
    c.keyOk = chargerUsed(cfg, i) && victronParseKey(cfg.chKey[i], c.key);
  }
}

// ------------------------------------------------------------ screen chip detection
// Reads the screen chip's ID with slow, simple pin toggling (before the fast bus starts).
// Current XC4630 shields use an ILI9341, older ones a UC8230.
static const uint8_t LCD_DATA[8] = {8, 9, 2, 3, 4, 5, 6, 7};
static void lcdW8(uint8_t d) {
  for (int i = 0; i < 8; i++) digitalWrite(LCD_DATA[i], (d >> i) & 1);
  digitalWrite(A1, LOW); delayMicroseconds(1); digitalWrite(A1, HIGH);
}
static uint8_t lcdR8() {
  digitalWrite(A0, LOW); delayMicroseconds(3);
  uint8_t v = 0;
  for (int i = 0; i < 8; i++) v |= digitalRead(LCD_DATA[i]) << i;
  digitalWrite(A0, HIGH); delayMicroseconds(2);
  return v;
}
static void lcdReset() {
  digitalWrite(A4, HIGH); delay(20);
  digitalWrite(A4, LOW);  delay(50);
  digitalWrite(A4, HIGH); delay(120);
}
// Sends a command (1 or 2 bytes) and reads n bytes back.
static void lcdRead(const uint8_t *cmd, int cmdLen, uint8_t *out, int n) {
  digitalWrite(A3, LOW);
  digitalWrite(A2, LOW);
  for (int i = 0; i < cmdLen; i++) lcdW8(cmd[i]);
  digitalWrite(A2, HIGH);
  for (int i = 0; i < 8; i++) pinMode(LCD_DATA[i], INPUT);
  delay(1);
  for (int i = 0; i < n; i++) out[i] = lcdR8();
  for (int i = 0; i < 8; i++) pinMode(LCD_DATA[i], OUTPUT);
  digitalWrite(A3, HIGH);
}
static uint16_t detectLcdChip() {
  for (int p = A0; p <= A4; p++) { pinMode(p, OUTPUT); digitalWrite(p, HIGH); }
  for (int i = 0; i < 8; i++) pinMode(LCD_DATA[i], OUTPUT);
  // UC8230: 16-bit register 0x0000 holds its ID
  lcdReset();
  const uint8_t reg0[2] = {0x00, 0x00};
  uint8_t id[4];
  lcdRead(reg0, 2, id, 2);
  uint16_t id16 = (id[0] << 8) | id[1];
  // ILI9341: command 0xD3 returns dummy, 0x00, 0x93, 0x41
  lcdReset();
  const uint8_t d3 = 0xD3;
  lcdRead(&d3, 1, id, 4);
  Serial.print("Screen chip ID: reg0=0x"); Serial.print(id16, HEX);
  Serial.print(" D3="); for (int i = 0; i < 4; i++) { Serial.print(' '); Serial.print(id[i], HEX); }
  Serial.println();
  if (id[2] == 0x93 && id[3] == 0x41) return 9341;
  if (id16 == 0x8230) return 8230;
  return 0;
}

// Redraw the whole dashboard (after leaving the settings screens)
void redrawDashboard() {
  dashDrawStatic(touchHW.ok, chargerCount(cfg) > 0);
  dashInvalidate();
}

void wakeScreen() {
  screenDark = false;
  Serial.println("Screen woken");
  redrawDashboard();
}

void openSettings() {
  if (!cfg.touchCalOk && !runCalibration()) { redrawDashboard(); return; }
  runSettings();
  waitRelease();
  redrawDashboard();
}

// ------------------------------------------------------------ main
void setup() {
  Serial.begin(115200);

  // Settings from the SD card (before the screen, which needs the chip type)
  cfgSource = loadConfig(cfg, cfgBadLines);
  const char *srcName[] = {"SD card", "defaults (no SD card, nothing in memory)", "defaults (CONFIG.TXT written)",
                           "defaults (can't open CONFIG.TXT)", "built-in memory (no SD card)", "built-in memory (copied to CONFIG.TXT)"};
  Serial.print("Settings from: "); Serial.println(srcName[cfgSource]);
  Serial.print("  mac="); Serial.print(cfg.mac); Serial.print(" demo="); Serial.print(cfg.demo);
  Serial.print(" rotation="); Serial.print(cfg.rotation); Serial.print(" lcd_chip="); Serial.println(cfg.lcdChip);
  if (cfgBadLines) { Serial.print("  lines not understood: "); Serial.println(cfgBadLines); }

  // Find the touch panel's pins (before the screen starts using them)
  if (detectTouchPins()) {
    Serial.print("Touch panel on D"); Serial.print(touchHW.dA); Serial.print("/A"); Serial.print(touchHW.aA - A0);
    Serial.print(" and D"); Serial.print(touchHW.dB); Serial.print("/A"); Serial.println(touchHW.aB - A0);
  } else Serial.println("Touch panel not found - settings can only be changed in CONFIG.TXT");
  if (cfg.touchCalOk) {
    Serial.print("Touch calibration: rot="); Serial.print(cfg.tRot); Serial.print(" swap="); Serial.print(cfg.tSwap);
    Serial.print(" x "); Serial.print(cfg.tx0); Serial.print(".."); Serial.print(cfg.tx1);
    Serial.print(" y "); Serial.print(cfg.ty0); Serial.print(".."); Serial.println(cfg.ty1);
  } else Serial.println("Touch not calibrated yet - any tap starts calibration");

  // Which screen chip? Detected if possible, otherwise the lcd_chip setting.
  lcdChip = detectLcdChip();
  lcdDetected = lcdChip != 0;
  if (!lcdDetected) lcdChip = cfg.lcdChip;
  Serial.print("Using screen driver: "); Serial.print(lcdChip == 8230 ? "UC8230" : "ILI9341");
  Serial.println(lcdDetected ? " (detected)" : " (from the lcd_chip setting)");

  // A calibration made on a different screen won't fit this one
  uint8_t chipCode = lcdChip == 8230 ? 2 : 1;
  // (calibrations saved before this was recorded were all made on ILI9341 shields)
  if (cfg.touchCalOk && (cfg.calChip ? cfg.calChip : 1) != chipCode) {
    Serial.println("Touch calibration was made on a different screen - tap to recalibrate");
    cfg.touchCalOk = false;
  }

  if (lcdChip == 8230) tft = new Arduino_UC8230(bus, A4, cfg.rotation);
  else tft = new Arduino_ILI9341(bus, A4, cfg.rotation);
  if (!tft->begin()) Serial.println("Display init failed");
  tft->invertDisplay(cfg.invert);
  cv->begin(GFX_SKIP_OUTPUT_BEGIN);
  cv->setTextWrap(false);
  dashOut = tft;

  // Screen held at power-on: recalibrate the touch panel
  if (touchPressed()) {
    uiMessage("Touch calibration", "let go of the screen to start", C_TEXT);
    waitRelease();
    runCalibration();
  }
  redrawDashboard();

  keyOk = victronParseKey(cfg.key, key);
  setupChargers(nullptr);
  setupNeeded = !cfg.demo && configIsPlaceholder(cfg);
  if (bleWanted()) startBLE();
}

// Use new settings straight away (called by Save on the settings screen)
void applySettings(const Config &e) {
  bool rotChanged = e.rotation != cfg.rotation, invChanged = e.invert != cfg.invert;
  bool sourceChanged = strcmp(e.mac, cfg.mac) || strcmp(e.key, cfg.key) || e.demo != cfg.demo;
  Config n = e;   // keep the live touch calibration (it may have been redone meanwhile)
  n.touchCalOk = cfg.touchCalOk; n.tRot = cfg.tRot; n.tSwap = cfg.tSwap;
  n.tx0 = cfg.tx0; n.tx1 = cfg.tx1; n.ty0 = cfg.ty0; n.ty1 = cfg.ty1; n.calChip = cfg.calChip;
  Config old = cfg;
  cfg = n;
  keyOk = victronParseKey(cfg.key, key);
  setupChargers(&old);
  setupNeeded = !cfg.demo && configIsPlaceholder(cfg);
  if (sourceChanged) { reading = ShuntReading(); lastHeard = 0; lastBadKey = 0; }
  if (rotChanged) tft->setRotation(cfg.rotation);
  if (invChanged) tft->invertDisplay(cfg.invert);
  if (bleWanted() && !bleStarted) startBLE();
}

void loop() {
  static uint32_t lastDraw = 0, lastFrame = 0, lastRescan = 0, lastTouchPoll = 0;

  // Touch: wake the screen, or tap the cog for settings.
  // Before the touch panel is calibrated, any tap starts calibration.
  if (touchHW.ok && millis() - lastTouchPoll > 50) {
    lastTouchPoll = millis();
    if (touchPressed()) {
      lastTouchAt = millis();
      int x, y;
      if (screenDark) {                        // this tap only wakes the screen
        wakeScreen();
        waitRelease();
        return;
      }
      if (!cfg.touchCalOk) {
        Serial.println("Starting touch calibration");
        openSettings();
        lastTouchAt = millis();
        return;
      }
      if (touchXY(x, y) && x >= COG_X - 30 && y <= COG_Y + 22) {
        drawCog(COG_X, COG_Y, C_TEXT, C_BG);   // light up while pressed
        waitRelease();
        openSettings();
        lastTouchAt = millis();
        return;
      }
    }
  }

  // Screen timeout (the XC4630's backlight can't be switched, so the screen goes black)
  if (!screenDark && cfg.screenOffS && !setupNeeded && millis() - lastTouchAt > cfg.screenOffS * 1000UL) {
    screenDark = true;
    tft->fillScreen(0x0000);   // black: the backlight stays on, but nothing is lit up
    Serial.println("Screen timeout: screen blanked (tap to wake)");
  }

  if (cfg.demo) demoTick();
  else if (setupNeeded) { /* waiting for a real MAC/key in CONFIG.TXT */ }
  else if (!bleStarted) {
    if (millis() > bleRetryAt) startBLE();
  } else {
    BLE.poll();
    // Some BLE firmware quietly stops scanning; restart if the shunt goes silent.
    uint32_t since = millis() - (lastHeard ? lastHeard : lastRescan);
    if (since > 15000 && millis() - lastRescan > 15000) {
      startScan();
      lastRescan = millis();
    }
  }

  if (screenDark) {
    // Wake up by itself if the shunt raises an alarm
    if (reading.alarm && lastHeard && millis() - lastHeard < 5000) { wakeScreen(); lastTouchAt = millis(); }
    return;
  }

  // The flow dots, about 25 times a second
  if (millis() - lastFrame >= 40) {
    lastFrame = millis();
    dashAnimate(dash, lastFrame);
  }

  if (millis() - lastDraw < 250) return;
  lastDraw = millis();
  buildState();
  dashUpdate(dash);
}

// ------------------------------------------------------------ what to show
// A Victron charger's operation mode as a charge stage, or "".
const char *stageName(int state) {
  switch (state) {
    case 0: case 1: return "Off";
    case 2: return "Fault";
    case 3: return "Bulk";
    case 4: case 246: case 248: return "Absorption";
    case 5: return "Float";
    case 6: return "Storage";
    case 7: case 247: return "Recondition";
    case 11: return "Power supply";
    case 245: return "Starting";
    default: return "";
  }
}

// The charge sources (top, left) and the loads (right); the same rules as the other versions.
// The shunt measures only the battery (pw, + charging). Each extra Victron charger reports its
// own output, so with K watts coming from them, the loads take K - pw when that's positive, and
// anything the battery gets beyond K came from a charger the display can't hear (the "other"
// node). With no extra chargers it's the plain picture: charging comes from the charger,
// discharging goes to the loads.
void flowNodes(DashState &s, float pw) {
  bool known = !isnan(pw);
  const uint8_t places[2] = {P_LEFT, P_TOP};
  int count = 0;
  float total = 0;
  s.has[P_LEFT] = false;
  for (int i = 0; i < CHARGER_SLOTS; i++) {
    if (!chargerUsed(cfg, i)) continue;
    const ChargerSlot &c = chargers[i];
    const ChargerReading &cr = c.reading;
    bool fresh = c.heard && millis() - c.heard <= (uint32_t)cfg.staleAfterS * 1000;
    float watts = fresh && cr.valid && !isnan(cr.power) ? (cr.power > 0 ? cr.power : 0) : NAN;
    if (!isnan(watts)) total += watts;
    int k = places[count++];
    s.has[k] = true;
    uint8_t kind = cr.valid ? cr.kind : 255;
    s.icon[k] = kind == CHG_SOLAR ? I_SUN : kind == CHG_DCDC ? I_CAR : I_PLUG;
    if (kind == CHG_MAINS) strcpy(s.label[k], "Mains");
    else if (kind == CHG_SOLAR) strcpy(s.label[k], "Solar");
    else if (kind == CHG_DCDC) strcpy(s.label[k], "DC-DC");
    else snprintf(s.label[k], sizeof(s.label[0]), "Charger %d", i + 1);
    s.extraColor[k] = C_MUTED;
    if (!fresh) {
      bool badKey = !c.keyOk || (c.badKey && millis() - c.badKey < 10000);
      strcpy(s.extra[k], badKey ? "Bad key" : c.heard ? "No signal" : "Searching");
      s.extraColor[k] = C_AMBER;
    } else if (cr.error > 0) {
      snprintf(s.extra[k], sizeof(s.extra[0]), "Error %d", cr.error);
      s.extraColor[k] = C_RED;
    } else strcpy(s.extra[k], stageName(cr.state));
    fmtPower(s.value[k], sizeof(s.value[0]), watts);
    s.flow[k] = isnan(watts) ? 0 : watts;
  }
  float other, loads;
  if (!count) {
    other = known && pw > 3 ? pw : 0;
    loads = known && pw < -3 ? -pw : 0;
  } else {
    other = pw - total > 0 ? pw - total : 0;
    loads = total - pw > 0 ? total - pw : 0;
  }
  if (!known) other = loads = NAN;
  if (count < 2) {
    static const char *const NAMES[N_SOURCES] = {"Charger", "DC-DC", "Solar", "Mains", "Alternator"};
    static const uint8_t ICONS[N_SOURCES] = {I_PLUG, I_CAR, I_SUN, I_PLUG, I_CAR};
    uint8_t src = cfg.otherSource < N_SOURCES ? cfg.otherSource : SRC_AUTO;
    s.has[P_TOP] = true;
    strcpy(s.label[P_TOP], src == SRC_AUTO && count ? "Other" : NAMES[src]);
    s.icon[P_TOP] = src == SRC_AUTO && count ? I_BOLT : ICONS[src];   // not a plug next to a mains charger's plug
    s.extra[P_TOP][0] = 0;
    s.extraColor[P_TOP] = C_MUTED;
    fmtPower(s.value[P_TOP], sizeof(s.value[0]), other);
    s.flow[P_TOP] = other;
  }
  s.has[P_RIGHT] = true;
  s.icon[P_RIGHT] = cfg.loadsIcon == 1 ? I_CARAVAN : cfg.loadsIcon == 2 ? I_BOAT : I_HOUSE;
  strcpy(s.label[P_RIGHT], "Loads");
  fmtPower(s.value[P_RIGHT], sizeof(s.value[0]), loads);
  s.flow[P_RIGHT] = -loads;
}

void buildState() {
  DashState &s = dash;
  const ShuntReading &r = reading;
  uint32_t age = lastHeard ? millis() - lastHeard : 0;
  bool stale = !lastHeard || age > (uint32_t)cfg.staleAfterS * 1000;
  s.stale = stale;
  uint16_t m = r.modelId;
  strcpy(s.title, m == 0xA380 ? "BMV-710" : m == 0xA381 || m == 0xA383 ? "BMV-712" : m == 0xA382 ? "BMV-710H" : "SmartShunt");

  // Charge
  if (isnan(r.soc)) strcpy(s.soc, "--"); else snprintf(s.soc, sizeof(s.soc), "%d%%", (int)(r.soc + 0.5f));
  s.socColor = stale ? C_MUTED : socColour(r.soc);
  s.bar = isnan(r.soc) ? -1 : r.soc;
  s.level = isnan(r.soc) ? -1 : r.soc;

  float cur = r.current;
  float pw = (isnan(r.voltage) || isnan(cur)) ? NAN : r.voltage * cur;   // + charging, - discharging
  bool known = !isnan(pw), charging = known && pw > 3, discharging = known && pw < -3;
  bool full = !isnan(r.soc) && r.soc >= 99.5f;

  // Time left (the shunt's own estimate), or the battery's state
  if (discharging) {
    strcpy(s.timeLabel, "Time left");
    if (r.remainingMins < 0) strcpy(s.time, "--");
    else {
      int mins = r.remainingMins, d = mins / 1440, h = (mins % 1440) / 60, mm = mins % 60;
      if (d) snprintf(s.time, sizeof(s.time), "%dd %dh", d, h);
      else snprintf(s.time, sizeof(s.time), "%dh %02dm", h, mm);
    }
  } else {
    strcpy(s.timeLabel, "Battery");
    strcpy(s.time, !known ? "--" : full ? "Full" : charging ? "Charging" : "Idle");
  }

  // Flow picture: + toward the hub
  flowNodes(s, pw);
  s.has[P_BOTTOM] = true;
  s.icon[P_BOTTOM] = I_BATTERY;
  s.flow[P_BOTTOM] = known ? -pw : NAN;
  fmtPower(s.value[P_BOTTOM], sizeof(s.value[0]), pw);
  strcpy(s.label[P_BOTTOM], charging ? "Charging" : discharging ? "Discharging" : "Battery");
  fmt(s.extra[P_BOTTOM], sizeof(s.extra[0]), r.voltage, 2, " V");
  s.extraColor[P_BOTTOM] = C_MUTED;

  // Readings
  uint16_t cTxt = stale ? C_MUTED : C_TEXT;
  uint16_t cCur = stale ? C_MUTED : (cur > 0.05f ? C_GREEN : cur < -0.05f ? C_AMBER : C_TEXT);
  fmt(s.read[0], sizeof(s.read[0]), r.voltage, 2, " V");      s.readColor[0] = cTxt;
  fmt(s.read[1], sizeof(s.read[1]), cur, 1, " A", true);      s.readColor[1] = cCur;
  fmt(s.read[2], sizeof(s.read[2]), pw, 0, " W", true);       s.readColor[2] = cCur;
  fmt(s.read[3], sizeof(s.read[3]), r.consumedAh, 1, " Ah");  s.readColor[3] = cTxt;
  s.auxMode = r.auxMode;
  if (r.auxMode == 2 || r.auxMode == 3) fmt(s.read[4], sizeof(s.read[4]), r.aux, 0, " ~C");   // '~' is drawn as a degree sign
  else fmt(s.read[4], sizeof(s.read[4]), r.aux, 2, " V");
  s.readColor[4] = cTxt;
  if (lastHeard && lastRssi) snprintf(s.read[5], sizeof(s.read[5]), "%d dBm", lastRssi); else strcpy(s.read[5], "--");
  s.readColor[5] = cTxt;
  for (int i = 0; i < 6; i++) if (!strcmp(s.read[i], "--")) s.readColor[i] = C_MUTED;

  // Status
  const char *msg; uint16_t col;
  bool badKey = !setupNeeded && (!keyOk || (lastBadKey && millis() - lastBadKey < 10000 && stale));
  if (cfg.demo)                     { msg = "OK";        col = C_GREEN; }
  else if (setupNeeded)             { msg = "Setup";     col = C_AMBER; }
  else if (bleFailed)               { msg = "BLE fail";  col = C_RED; }
  else if (badKey)                  { msg = "Bad key";   col = C_RED; }
  else if (!lastHeard)              { msg = "Searching"; col = C_AMBER; }
  else if (stale)                   { msg = "No signal"; col = C_AMBER; }
  else if (r.alarm)                 { msg = "ALARM";     col = C_RED; }
  else                              { msg = "OK";        col = C_GREEN; }
  strcpy(s.status, msg);
  s.statusColor = col;
  char *d = s.detail;
  if (cfg.demo) strcpy(d, "demo data");
  else if (setupNeeded) strcpy(d, touchHW.ok ? "tap the cog" : !cfgCardPresent(cfgSource) ? "insert SD card" : "edit config.txt");
  else if (bleFailed) strcpy(d, "retrying...");
  else if (badKey) strcpy(d, "check key");
  else if (cfgBadLines && !lastHeard) strcpy(d, "config error");
  else if (r.alarm && !stale) {
    const char *name = nullptr;
    for (int i = 0; i < 14 && !name; i++) if (r.alarm & (1 << i)) name = ALARM_NAMES[i];
    if (name) strcpy(d, name); else snprintf(d, sizeof(s.detail), "code 0x%04X", r.alarm);
  }
  else if (lastHeard) snprintf(d, sizeof(s.detail), "%lus ago", (unsigned long)(age / 1000));
  else d[0] = 0;
}
