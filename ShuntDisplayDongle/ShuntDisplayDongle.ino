// ============================================================================
//  Victron SmartShunt display — LILYGO T-Dongle-S3 (ESP32-S3, 0.96" 160x80 screen)
//
//  A basic battery readout from the shunt's Bluetooth "Instant Readout" broadcasts:
//  state of charge, voltage, current, power and consumed Ah, with a second page
//  (press the button) for the aux input, signal and the monitor's model.
//
//  Set up on a PC: put CONFIG.TXT on the microSD card (in the dongle's USB plug) with
//  your shunt's MAC address and key. A blank card gets a CONFIG.TXT to fill in.
//
//  Libraries (Arduino IDE > Library Manager): GFX Library for Arduino (Moon On Our Nation).
//  BLE, SD_MMC and Preferences come with the ESP32 core (version 3.x).
//  Board settings: see README.md.
// ============================================================================

#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <FS.h>
#include <SD_MMC.h>
#include <Preferences.h>
#include <Arduino_GFX_Library.h>
#include "victron.h"
#include "screen.h"

// ------------------------------------------------------------ T-Dongle-S3 pins
#define PIN_LCD_DC 2
#define PIN_LCD_CS 4
#define PIN_LCD_SCK 5
#define PIN_LCD_MOSI 3
#define PIN_LCD_RST 1
#define PIN_LCD_BL 38          // backlight, on when LOW
#define PIN_SD_CLK 12
#define PIN_SD_CMD 16
#define PIN_SD_D0 14
#define PIN_SD_D1 17
#define PIN_SD_D2 21
#define PIN_SD_D3 18
#define PIN_BUTTON 0           // the BOOT button
#define PIN_LED_DATA 40        // APA102 RGB LED
#define PIN_LED_CLOCK 39

#define CONFIG_PATH "/CONFIG.TXT"
#define PLACEHOLDER_MAC "aa:bb:cc:dd:ee:ff"
#define PLACEHOLDER_KEY "0123456789abcdef0123456789abcdef"

// ------------------------------------------------------------ settings
struct Config {
  char mac[18] = PLACEHOLDER_MAC;
  char key[33] = PLACEHOLDER_KEY;
  bool demo = false;
  uint16_t staleAfterS = 30;
  uint8_t socAmber = 50, socRed = 20;
  uint16_t screenOffS = 0;     // 0 = always on
  uint8_t rotation = 1;        // 1 or 3 (upside down)
  uint8_t brightness = 100;    // %
  bool led = true;             // the RGB LED shows the charge colour
};

Config cfg;
enum { CFG_SD, CFG_TEMPLATE, CFG_MEMORY, CFG_NONE } cfgFrom = CFG_NONE;
int cfgUnknown = 0;
Preferences prefs;

// Keeps only hex digits (dropping : - space .), lower-cased. False on anything else or the wrong count.
static bool hexOnly(const char *val, char *out, int want) {
  int n = 0;
  for (const char *p = val; *p; p++) {
    if (*p == ':' || *p == '-' || *p == ' ' || *p == '.') continue;
    if (!isxdigit((unsigned char)*p) || n >= want) return false;
    out[n++] = tolower((unsigned char)*p);
  }
  out[n] = 0;
  return n == want;
}

static void trim(char *s) {
  char *p = s;
  while (*p == ' ' || *p == '\t') p++;
  if (p != s) memmove(s, p, strlen(p) + 1);
  int n = strlen(s);
  while (n && (s[n - 1] == ' ' || s[n - 1] == '\t' || s[n - 1] == '\r' || s[n - 1] == '\n')) s[--n] = 0;
}

// One "name = value" line. Names this display doesn't use (the other versions' settings in a
// shared CONFIG.TXT) are skipped; returns false only for a bad value.
static bool cfgLine(Config &c, char *line) {
  char *hash = strchr(line, '#');
  if (hash) *hash = 0;
  trim(line);
  if (!*line) return true;
  char *eq = strchr(line, '=');
  if (!eq) return false;
  *eq = 0;
  char *name = line, *val = eq + 1;
  trim(name); trim(val);
  long n = atol(val);
  if (!strcasecmp(name, "mac")) {
    char hex[13];
    if (!hexOnly(val, hex, 12)) return false;
    for (int i = 0; i < 6; i++) { c.mac[i * 3] = hex[i * 2]; c.mac[i * 3 + 1] = hex[i * 2 + 1]; c.mac[i * 3 + 2] = i < 5 ? ':' : 0; }
  } else if (!strcasecmp(name, "key")) {
    char hex[33];
    if (!hexOnly(val, hex, 32)) return false;
    strcpy(c.key, hex);
  } else if (!strcasecmp(name, "demo")) c.demo = n != 0;
  else if (!strcasecmp(name, "stale_after")) { if (n < 2) return false; c.staleAfterS = n; }
  else if (!strcasecmp(name, "soc_amber")) c.socAmber = constrain(n, 0L, 100L);
  else if (!strcasecmp(name, "soc_red")) c.socRed = constrain(n, 0L, 100L);
  else if (!strcasecmp(name, "screen_off")) { if (n < 0) return false; c.screenOffS = n; }
  else if (!strcasecmp(name, "dongle_rotation")) { if (n != 1 && n != 3) return false; c.rotation = n; }
  else if (!strcasecmp(name, "brightness")) c.brightness = constrain(n, 5L, 100L);
  else if (!strcasecmp(name, "led")) c.led = n != 0;
  else { cfgUnknown++; Serial.printf("  (not used here: %s)\n", name); }
  return true;
}

static void cfgWrite(File &f, const Config &c) {
  f.print("# SmartShunt display settings (T-Dongle-S3)\r\n"
          "# Lines starting with # are ignored. Unplug and replug the dongle after editing.\r\n\r\n"
          "# From VictronConnect: SmartShunt > settings > ... > Product info >\r\n"
          "# Instant readout via Bluetooth > Show. With or without colons.\r\n");
  f.printf("mac = %s\r\nkey = %s\r\n\r\n", c.mac, c.key);
  f.print("# 1 = show fake data (to test the screen), 0 = read the shunt\r\n");
  f.printf("demo = %d\r\n\r\n", c.demo ? 1 : 0);
  f.print("# Seconds without data before showing 'No signal'\r\n");
  f.printf("stale_after = %u\r\n", c.staleAfterS);
  f.print("# State of charge colours: amber below this %, red below the next\r\n");
  f.printf("soc_amber = %u\r\nsoc_red = %u\r\n\r\n", c.socAmber, c.socRed);
  f.print("# Seconds before the screen turns off (the button wakes it). 0 = always on\r\n");
  f.printf("screen_off = %u\r\n", c.screenOffS);
  f.print("# Screen brightness, 5-100 %\r\n");
  f.printf("brightness = %u\r\n", c.brightness);
  f.print("# Screen: 1 = normal, 3 = upside down\r\n");
  f.printf("dongle_rotation = %u\r\n", c.rotation);
  f.print("# 1 = the RGB LED shows the charge colour (green, amber, red), 0 = off\r\n");
  f.printf("led = %d\r\n", c.led ? 1 : 0);
}

// CONFIG.TXT on the card, then the copy in the built-in memory, then the defaults.
// A good file is copied to the built-in memory, so the card can be taken out afterwards.
static void loadConfig() {
  prefs.begin("shunt", false);
  SD_MMC.setPins(PIN_SD_CLK, PIN_SD_CMD, PIN_SD_D0, PIN_SD_D1, PIN_SD_D2, PIN_SD_D3);
  bool card = SD_MMC.begin("/sdcard", false);
  if (!card) card = SD_MMC.begin("/sdcard", true);          // some cards only work in 1-bit mode
  if (card) {
    if (SD_MMC.exists(CONFIG_PATH)) {
      File f = SD_MMC.open(CONFIG_PATH, FILE_READ);
      if (f) {
        Config c;
        char line[128];
        int len = 0, bad = 0;
        while (true) {
          int ch = f.read();
          if (ch == '\n' || ch < 0) {
            line[len] = 0;
            if (!cfgLine(c, line)) bad++;
            len = 0;
            if (ch < 0) break;
          } else if (len < (int)sizeof(line) - 1) line[len++] = (char)ch;
        }
        f.close();
        cfg = c;
        cfgFrom = CFG_SD;
        prefs.putBytes("cfg", &cfg, sizeof(cfg));
        Serial.printf("Settings from CONFIG.TXT (%d bad lines)\n", bad);
      }
    } else {                                                  // blank card: write one to fill in
      Config c;
      size_t n = prefs.getBytesLength("cfg") == sizeof(Config) ? prefs.getBytes("cfg", &c, sizeof(c)) : 0;
      File f = SD_MMC.open(CONFIG_PATH, FILE_WRITE);
      if (f) { cfgWrite(f, c); f.close(); }
      cfg = c;
      cfgFrom = n ? CFG_MEMORY : CFG_TEMPLATE;
      Serial.println("No CONFIG.TXT: wrote one to the card");
    }
    SD_MMC.end();
  }
  if (cfgFrom == CFG_NONE && prefs.getBytesLength("cfg") == sizeof(Config)) {
    prefs.getBytes("cfg", &cfg, sizeof(cfg));
    cfg.mac[17] = 0; cfg.key[32] = 0;
    cfgFrom = CFG_MEMORY;
    Serial.println("No SD card: settings from the built-in memory");
  }
  if (cfgFrom == CFG_NONE) Serial.println("No SD card and nothing saved: defaults");
}

static bool needsSetup() {
  return !cfg.demo && (!strcasecmp(cfg.mac, PLACEHOLDER_MAC) || !strcmp(cfg.key, PLACEHOLDER_KEY));
}

// ------------------------------------------------------------ screen
Arduino_DataBus *bus = new Arduino_ESP32SPI(PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_MOSI, GFX_NOT_DEFINED);
Arduino_GFX *lcd = nullptr;
Arduino_Canvas *canvas = nullptr;

static void backlight(uint8_t percent) {
  analogWrite(PIN_LCD_BL, 255 - (int)percent * 255 / 100);   // active low
}

// ------------------------------------------------------------ RGB LED (APA102)
static void ledShift(uint8_t b) {
  for (int i = 7; i >= 0; i--) {
    digitalWrite(PIN_LED_DATA, (b >> i) & 1);
    digitalWrite(PIN_LED_CLOCK, HIGH);
    digitalWrite(PIN_LED_CLOCK, LOW);
  }
}
static void ledSet(uint8_t r, uint8_t g, uint8_t b) {
  static uint32_t last = 0xFFFFFFFF;
  uint32_t v = ((uint32_t)r << 16) | (g << 8) | b;
  if (v == last) return;
  last = v;
  for (int i = 0; i < 4; i++) ledShift(0);                // start frame
  ledShift(0xE0 | 2);                                      // dim: brightness 2 of 31
  ledShift(b); ledShift(g); ledShift(r);                   // BGR order
  for (int i = 0; i < 4; i++) ledShift(0xFF);              // end frame
}

// ------------------------------------------------------------ Bluetooth
// The scan callback runs on the Bluetooth task: it only copies the shunt's packet here, and
// loop() decodes it.
portMUX_TYPE pktLock = portMUX_INITIALIZER_UNLOCKED;
uint8_t pkt[32];
int pktLen = 0, pktRssi = 0;
volatile bool pktNew = false;

class ScanCallback : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) override {
    if (!dev.haveManufacturerData()) return;
    if (strcasecmp(dev.getAddress().toString().c_str(), cfg.mac)) return;
    auto md = dev.getManufacturerData();
    int n = md.length();
    if (n < 10 || (uint8_t)md[0] != 0xE1 || (uint8_t)md[1] != 0x02) return;   // Victron company ID 0x02E1
    if (n - 2 > (int)sizeof(pkt)) n = sizeof(pkt) + 2;
    portENTER_CRITICAL(&pktLock);
    for (int i = 2; i < n; i++) pkt[i - 2] = (uint8_t)md[i];
    pktLen = n - 2;
    pktRssi = dev.getRSSI();
    pktNew = true;
    portEXIT_CRITICAL(&pktLock);
  }
};

BLEScan *scan = nullptr;

static void startScan() {
  if (!scan) return;
  scan->stop();
  scan->clearResults();
  scan->start(0, nullptr, false);       // 0 = keep scanning
}

// ------------------------------------------------------------ live state
ShuntReading reading;
uint8_t key[16];
bool keyOk = false;
uint32_t lastHeard = 0, lastBadKey = 0, lastRescan = 0, lastPress = 0;
int lastRssi = 0;
int page = 0;
bool screenOn = true;

static const char *ALARM_NAMES[14] = {"Low voltage", "High voltage", "Low SOC", "Low starter V", "High starter V",
                                      "Low temp", "High temp", "Midpoint V", "Overload", "DC ripple",
                                      "Low AC out", "High AC out", "Short circuit", "BMS lockout"};

static void fmt(char *buf, size_t n, float v, int decimals, const char *unit, bool sign = false) {
  if (isnan(v)) { snprintf(buf, n, "--"); return; }
  char num[16];
  snprintf(num, sizeof(num), "%s%.*f", sign && v > 0 ? "+" : "", decimals, v);
  if (!strncmp(num, "-0", 2) && atof(num) == 0) memmove(num, num + 1, strlen(num));
  snprintf(buf, n, "%s%s", num, unit);
}

static void demoTick() {
  float t = millis() / 1000.0f, cur = -8.5f + 14 * sinf(t / 20);
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
}

static void buildState(DongleState &s) {
  const ShuntReading &r = reading;
  uint32_t age = lastHeard ? millis() - lastHeard : 0;
  bool stale = !lastHeard || age > (uint32_t)cfg.staleAfterS * 1000;
  s = DongleState();
  s.valColor = stale ? C_MUTED : C_TEXT;
  if (!isnan(r.soc)) snprintf(s.soc, sizeof(s.soc), "%d", (int)(r.soc + 0.5f));
  s.socColor = stale || isnan(r.soc) ? C_MUTED : r.soc >= cfg.socAmber ? C_GREEN : r.soc >= cfg.socRed ? C_AMBER : C_RED;
  s.bar = isnan(r.soc) ? -1 : r.soc;
  float pw = isnan(r.voltage) || isnan(r.current) ? NAN : r.voltage * r.current;
  bool known = !isnan(pw), charging = known && pw > 3, discharging = known && pw < -3;
  if (discharging && r.remainingMins >= 0) {
    int m = r.remainingMins, d = m / 1440, h = (m % 1440) / 60, mm = m % 60;
    if (d) snprintf(s.time, sizeof(s.time), "%dd %dh", d, h);
    else snprintf(s.time, sizeof(s.time), "%dh %02dm", h, mm);
  } else if (known) {
    strcpy(s.time, !isnan(r.soc) && r.soc >= 99.5f ? "Full" : charging ? "Charging" : discharging ? "Discharging" : "Idle");
  }
  fmt(s.volt, sizeof(s.volt), r.voltage, 2, " V");
  fmt(s.amps, sizeof(s.amps), r.current, 1, " A", true);
  fmt(s.watts, sizeof(s.watts), pw, 0, " W", true);
  fmt(s.cons, sizeof(s.cons), r.consumedAh, 1, " Ah");
  s.curColor = stale ? C_MUTED : r.current > 0.05f ? C_GREEN : r.current < -0.05f ? C_AMBER : C_TEXT;
  // page 2
  if (r.auxMode == 0) { strcpy(s.auxLabel, "Starter"); fmt(s.aux, sizeof(s.aux), r.aux, 2, " V"); }
  else if (r.auxMode == 1) { strcpy(s.auxLabel, "Midpoint"); fmt(s.aux, sizeof(s.aux), r.aux, 2, " V"); }
  else { strcpy(s.auxLabel, "Temp"); fmt(s.aux, sizeof(s.aux), r.aux, 0, " ~C"); }   // '~' is a degree sign
  if (lastHeard && lastRssi) snprintf(s.signal, sizeof(s.signal), "%d dBm", lastRssi);
  if (lastHeard) snprintf(s.age, sizeof(s.age), "%lus ago", (unsigned long)(age / 1000));
  uint16_t m = r.modelId;
  strcpy(s.model, m == 0xA380 ? "BMV-710" : m == 0xA381 || m == 0xA383 ? "BMV-712" : m == 0xA382 ? "BMV-710H" : "SmartShunt");
  // status
  bool badKey = !keyOk || (lastBadKey && millis() - lastBadKey < 10000 && stale);
  if (cfg.demo) { strcpy(s.status, "Demo"); s.statusColor = C_GREEN; }
  else if (badKey) { strcpy(s.status, "Bad key"); s.statusColor = C_RED; }
  else if (!lastHeard) { strcpy(s.status, "Searching"); s.statusColor = C_AMBER; }
  else if (stale) { snprintf(s.status, sizeof(s.status), "No signal"); s.statusColor = C_AMBER; }
  else if (r.alarm) {
    const char *name = nullptr;
    for (int i = 0; i < 14 && !name; i++) if (r.alarm & (1 << i)) name = ALARM_NAMES[i];
    snprintf(s.status, sizeof(s.status), "%s", name ? name : "ALARM");
    s.statusColor = C_RED;
  } else { snprintf(s.status, sizeof(s.status), "OK %lus", (unsigned long)(age / 1000)); s.statusColor = C_GREEN; }
  // the LED: the charge colour, red while there's an alarm, off without data
  if (cfg.led) {
    if (stale || isnan(r.soc)) ledSet(0, 0, 0);
    else if (r.alarm || s.socColor == C_RED) ledSet(255, 0, 0);
    else if (s.socColor == C_AMBER) ledSet(255, 110, 0);
    else ledSet(0, 255, 0);
  }
}

static void draw() {
  if (needsSetup()) {
    if (cfgFrom == CFG_NONE) drawMessage(canvas, "Insert SD card", C_AMBER, "with CONFIG.TXT on it,", "then replug the dongle");
    else drawMessage(canvas, "Setup", C_AMBER, "Edit CONFIG.TXT on the card:", "the shunt's mac and key");
  } else {
    DongleState s;
    buildState(s);
    if (page == 0) drawPage1(canvas, s); else drawPage2(canvas, s);
  }
  canvas->flush();
}

// ------------------------------------------------------------ main
void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED_DATA, OUTPUT);
  pinMode(PIN_LED_CLOCK, OUTPUT);
  ledSet(0, 0, 0);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);                     // dark until the screen is ready

  loadConfig();
  Serial.printf("mac=%s demo=%d\n", cfg.mac, cfg.demo);
  if (!cfg.led) ledSet(0, 0, 0);

  // 0.96" IPS ST7735, 80x160 with a 26/1 pixel offset; landscape
  lcd = new Arduino_ST7735(bus, PIN_LCD_RST, cfg.rotation, true, 80, 160, 26, 1, 26, 1);
  canvas = new Arduino_Canvas(160, 80, lcd);
  if (!canvas->begin()) Serial.println("Screen didn't start");
  canvas->setTextWrap(false);
  draw();
  backlight(cfg.brightness);

  keyOk = victronParseKey(cfg.key, key);
  if (!cfg.demo && !needsSetup()) {
    BLEDevice::init("");
    scan = BLEDevice::getScan();
    scan->setAdvertisedDeviceCallbacks(new ScanCallback(), true);   // true: every advertisement
    scan->setActiveScan(false);
    scan->setInterval(100);
    scan->setWindow(99);
    startScan();
    lastRescan = millis();
    Serial.println("Scanning");
  }
  lastPress = millis();
}

void loop() {
  static uint32_t lastDraw = 0;
  static bool wasDown = false;

  // the button: wakes the screen, or switches page
  bool down = digitalRead(PIN_BUTTON) == LOW;
  if (down && !wasDown && millis() - lastPress > 150) {
    lastPress = millis();
    if (!screenOn) { screenOn = true; backlight(cfg.brightness); }
    else page = 1 - page;
    lastDraw = 0;
  }
  wasDown = down;

  if (cfg.demo) demoTick();

  // a packet from the shunt
  if (pktNew) {
    uint8_t d[32];
    int n, rssi;
    portENTER_CRITICAL(&pktLock);
    n = pktLen; rssi = pktRssi;
    memcpy(d, pkt, n);
    pktNew = false;
    portEXIT_CRITICAL(&pktLock);
    ShuntReading r;
    VictronResult res = keyOk ? victronDecode(d, n, key, r) : VIC_BAD_KEY;
    if (res == VIC_OK) { reading = r; lastHeard = millis() ? millis() : 1; lastRssi = rssi; }
    else if (res == VIC_BAD_KEY) lastBadKey = millis();
  }

  // restart the scan if the shunt has gone quiet for a minute (some scans stall)
  if (scan && millis() - (lastHeard > lastRescan ? lastHeard : lastRescan) > 60000) {
    startScan();
    lastRescan = millis();
    Serial.println("Restarted the scan");
  }

  // screen timeout; an alarm wakes it
  bool alarm = reading.alarm && lastHeard && millis() - lastHeard < 10000;
  if (screenOn && cfg.screenOffS && !alarm && millis() - lastPress > cfg.screenOffS * 1000UL) {
    screenOn = false;
    backlight(0);
  } else if (!screenOn && alarm) {
    screenOn = true;
    lastPress = millis();
    backlight(cfg.brightness);
  }

  if (screenOn && millis() - lastDraw >= 500) {
    lastDraw = millis();
    draw();
  }
  delay(10);
}
