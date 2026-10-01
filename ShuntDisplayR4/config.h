// Settings: stored in CONFIG.TXT on the display's SD card and in the R4's own EEPROM
// (built-in flash that keeps its contents without power), so they survive without a card.
// They can be edited on a computer, or on the display itself (tap the cog).
#pragma once
#include <SPI.h>
#include <SD.h>
#include <EEPROM.h>
#include <ctype.h>
#include <stdio.h>

#define SD_CS_PIN 10
#define CONFIG_FILE "CONFIG.TXT"
#define PLACEHOLDER_MAC "aa:bb:cc:dd:ee:ff"
#define PLACEHOLDER_KEY "0123456789abcdef0123456789abcdef"

// The settings from before extra chargers were added. Kept as their own struct, because it's
// also the layout of settings saved in the built-in memory by earlier versions (see eepromLoad).
struct ConfigV1 {
  char mac[18] = PLACEHOLDER_MAC;
  char key[33] = PLACEHOLDER_KEY;
  bool demo = false;
  uint8_t rotation = 1;
  uint16_t lcdChip = 9341;     // only used if the chip can't be detected
  bool invert = false;
  uint16_t staleAfterS = 30;
  uint8_t socAmber = 50;
  uint8_t socRed = 20;
  uint16_t screenOffS = 30;     // 0 = screen always on
  // Touch calibration: raw readings at screen x=0 / x=319 and y=0 / y=239,
  // whether the raw axes are swapped, and the rotation it was taken in.
  bool touchCalOk = false;
  uint8_t tRot = 1;
  bool tSwap = false;
  uint8_t calChip = 0;          // screen chip the calibration was made on: 1 = ILI9341, 2 = UC8230, 0 = unknown
  int16_t tx0 = 0, tx1 = 0, ty0 = 0, ty1 = 0;
};

// Up to two extra Victron chargers (Blue Smart IP22, SmartSolar MPPT, Orion XS). "" = not used.
#define CHARGER_SLOTS 2
// What to call charging the extra chargers don't account for
enum { SRC_AUTO, SRC_DCDC, SRC_SOLAR, SRC_MAINS, SRC_ALTERNATOR, N_SOURCES };
static const char *const SOURCE_WORDS[N_SOURCES] = {"auto", "dcdc", "solar", "mains", "alternator"};
enum { N_LOADS_ICONS = 3 };
static const char *const LOADS_ICON_WORDS[N_LOADS_ICONS] = {"house", "caravan", "boat"};

struct Config : ConfigV1 {
  char chMac[CHARGER_SLOTS][18] = {"", ""};
  char chKey[CHARGER_SLOTS][33] = {"", ""};
  uint8_t otherSource = SRC_AUTO;
  uint8_t loadsIcon = 0;        // picture on the Loads node: 0 house, 1 caravan, 2 boat
};
// loadsIcon sits in what was the struct's last padding byte, so settings saved by the version
// with chargers (same size) still load; eepromLoad() checks the value.

static bool chargerUsed(const Config &c, int i) { return c.chMac[i][0] && c.chKey[i][0]; }
static int chargerCount(const Config &c) {
  int n = 0;
  for (int i = 0; i < CHARGER_SLOTS; i++) n += chargerUsed(c, i);
  return n;
}

enum ConfigSource {
  CFG_FROM_SD,           // read CONFIG.TXT (and copied it to the built-in memory)
  CFG_NO_CARD,           // no card, nothing saved in memory yet: defaults
  CFG_TEMPLATE_WRITTEN,  // blank card, nothing in memory: wrote a CONFIG.TXT with the defaults
  CFG_NO_FILE,           // card present but CONFIG.TXT couldn't be read or written
  CFG_FROM_MEMORY,       // no card: used the settings saved in the built-in memory
  CFG_MEMORY_TO_SD,      // blank card: wrote CONFIG.TXT from the built-in memory
};
static bool cfgCardPresent(ConfigSource s) { return s != CFG_NO_CARD && s != CFG_FROM_MEMORY; }

// Keep only hex digits (dropping : - space .), lower-cased. Returns false on any other character
// or if the count isn't exactly `want`.
static bool cfgHex(const char *val, char *out, int want) {
  int n = 0;
  for (const char *p = val; *p; p++) {
    if (*p == ':' || *p == '-' || *p == ' ' || *p == '.') continue;
    if (!isxdigit((unsigned char)*p) || n >= want) return false;
    out[n++] = tolower((unsigned char)*p);
  }
  out[n] = 0;
  return n == want;
}

// 12 hex digits -> "aa:bb:cc:dd:ee:ff"
static void cfgFormatMac(const char *hex12, char *mac) {
  for (int i = 0; i < 6; i++) {
    mac[i * 3] = hex12[i * 2];
    mac[i * 3 + 1] = hex12[i * 2 + 1];
    mac[i * 3 + 2] = i < 5 ? ':' : 0;
  }
}

static void cfgTrim(char *s) {
  char *p = s;
  while (*p == ' ' || *p == '\t') p++;
  if (p != s) memmove(s, p, strlen(p) + 1);
  int n = strlen(s);
  while (n && (s[n - 1] == ' ' || s[n - 1] == '\t' || s[n - 1] == '\r' || s[n - 1] == '\n')) s[--n] = 0;
}

// Returns false if the line had a setting name we don't know or a bad value.
static bool cfgApply(Config &c, const char *name, const char *val) {
  long n = atol(val);
  // charger1_mac, charger1_key, charger2_mac, charger2_key (blank = not used)
  if (!strncasecmp(name, "charger", 7) && name[7] >= '1' && name[7] < '1' + CHARGER_SLOTS
      && (!strcasecmp(name + 8, "_mac") || !strcasecmp(name + 8, "_key"))) {
    int i = name[7] - '1';
    bool isMac = !strcasecmp(name + 8, "_mac");
    if (!*val) { (isMac ? c.chMac[i] : c.chKey[i])[0] = 0; return true; }
    char hex[33];
    if (!cfgHex(val, hex, isMac ? 12 : 32)) return false;
    if (isMac) cfgFormatMac(hex, c.chMac[i]); else strcpy(c.chKey[i], hex);
    return true;
  }
  if (!strcasecmp(name, "loads_icon")) {
    for (int i = 0; i < N_LOADS_ICONS; i++) if (!strcasecmp(val, LOADS_ICON_WORDS[i])) { c.loadsIcon = i; return true; }
    return false;
  }
  if (!strcasecmp(name, "other_source")) {
    for (int i = 0; i < N_SOURCES; i++) if (!strcasecmp(val, SOURCE_WORDS[i])) { c.otherSource = i; return true; }
    return false;
  }
  if (!strcasecmp(name, "mac")) {
    char hex[13];
    if (!cfgHex(val, hex, 12)) return false;
    cfgFormatMac(hex, c.mac);
  } else if (!strcasecmp(name, "key")) {
    char hex[33];
    if (!cfgHex(val, hex, 32)) return false;
    strcpy(c.key, hex);
  } else if (!strcasecmp(name, "demo"))        c.demo = n != 0;
  else if (!strcasecmp(name, "rotation"))      { if (n != 1 && n != 3) return false; c.rotation = n; }
  else if (!strcasecmp(name, "lcd_chip"))      { if (n != 9341 && n != 8230) return false; c.lcdChip = n; }
  else if (!strcasecmp(name, "invert"))        c.invert = n != 0;
  else if (!strcasecmp(name, "stale_after"))   { if (n < 2) return false; c.staleAfterS = n; }
  else if (!strcasecmp(name, "soc_amber"))     c.socAmber = constrain(n, 0L, 100L);
  else if (!strcasecmp(name, "soc_red"))       c.socRed = constrain(n, 0L, 100L);
  else if (!strcasecmp(name, "screen_off"))    { if (n < 0) return false; c.screenOffS = n; }
  else if (!strcasecmp(name, "touch_cal")) {
    int r, s, a, b, d, e, chip = 0;
    int got = sscanf(val, "%d , %d , %d , %d , %d , %d , %d", &r, &s, &a, &b, &d, &e, &chip);
    if (got < 6) return false;
    if ((r != 1 && r != 3) || a == b || d == e) return false;
    c.tRot = r; c.tSwap = s != 0; c.tx0 = a; c.tx1 = b; c.ty0 = d; c.ty1 = e;
    c.calChip = chip == 9341 ? 1 : chip == 8230 ? 2 : 0;
    c.touchCalOk = true;
  }
  else return false;
  return true;
}

// Parses one line "name = value   # comment".
static bool cfgLine(Config &c, char *line) {
  char *hash = strchr(line, '#');
  if (hash) *hash = 0;
  cfgTrim(line);
  if (!*line) return true;
  char *eq = strchr(line, '=');
  if (!eq) return false;
  *eq = 0;
  char *name = line, *val = eq + 1;
  cfgTrim(name); cfgTrim(val);
  return cfgApply(c, name, val);
}

// Writes the whole settings file (with explanations) for config `c` to any Print (file or Serial).
static void cfgWrite(Print &f, const Config &c) {
  f.print(F("# SmartShunt display settings\r\n"
            "# Edit here, or on the display: tap the cog in the top-right corner.\r\n"
            "# Lines starting with # are ignored. Restart the display after editing.\r\n\r\n"
            "# From VictronConnect: SmartShunt > settings > ... > Product info >\r\n"
            "# Instant readout via Bluetooth > Show\r\n"
            "# The MAC can be pasted as-is, with or without colons.\r\n"));
  f.print(F("mac = ")); f.print(c.mac); f.print(F("\r\n"));
  f.print(F("key = ")); f.print(c.key); f.print(F("\r\n\r\n"));
  f.print(F("# Extra Victron chargers (optional): Blue Smart IP22, SmartSolar MPPT or Orion XS,\r\n"
            "# with Instant readout turned on. MAC and key from VictronConnect, as for the shunt.\r\n"));
  for (int i = 0; i < CHARGER_SLOTS; i++) {
    if (!c.chMac[i][0] && !c.chKey[i][0]) continue;
    f.print(F("charger")); f.print(i + 1); f.print(F("_mac = ")); f.print(c.chMac[i]); f.print(F("\r\n"));
    f.print(F("charger")); f.print(i + 1); f.print(F("_key = ")); f.print(c.chKey[i]); f.print(F("\r\n"));
  }
  f.print(F("# Name for charging they don't account for: auto, dcdc, solar, mains or alternator\r\n"));
  f.print(F("other_source = ")); f.print(SOURCE_WORDS[c.otherSource < N_SOURCES ? c.otherSource : 0]); f.print(F("\r\n\r\n"));
  f.print(F("# Picture on the Loads node: house, caravan or boat\r\n"));
  f.print(F("loads_icon = ")); f.print(LOADS_ICON_WORDS[c.loadsIcon < N_LOADS_ICONS ? c.loadsIcon : 0]); f.print(F("\r\n\r\n"));
  f.print(F("# 1 = show fake data (to test the screen), 0 = read the shunt\r\n"));
  f.print(F("demo = ")); f.print(c.demo ? 1 : 0); f.print(F("\r\n\r\n"));
  f.print(F("# Screen: 1 = landscape, 3 = landscape upside down\r\n"));
  f.print(F("rotation = ")); f.print(c.rotation); f.print(F("\r\n"));
  f.print(F("# Screen chip if it can't be detected automatically: 9341 (current XC4630) or 8230 (older)\r\n"));
  f.print(F("lcd_chip = ")); f.print(c.lcdChip); f.print(F("\r\n"));
  f.print(F("# 1 if colours look inverted\r\n"));
  f.print(F("invert = ")); f.print(c.invert ? 1 : 0); f.print(F("\r\n\r\n"));
  f.print(F("# Seconds without data before showing 'No signal'\r\n"));
  f.print(F("stale_after = ")); f.print(c.staleAfterS); f.print(F("\r\n"));
  f.print(F("# State of charge colours: amber below this %, red below the next\r\n"));
  f.print(F("soc_amber = ")); f.print(c.socAmber); f.print(F("\r\n"));
  f.print(F("soc_red = ")); f.print(c.socRed); f.print(F("\r\n\r\n"));
  f.print(F("# Seconds without a touch before the screen goes dark (a tap wakes it). 0 = always on\r\n"));
  f.print(F("screen_off = ")); f.print(c.screenOffS); f.print(F("\r\n"));
  if (c.touchCalOk) {
    char buf[64];
    snprintf(buf, sizeof(buf), "%d, %d, %d, %d, %d, %d, %d", c.tRot, c.tSwap ? 1 : 0, c.tx0, c.tx1, c.ty0, c.ty1,
             c.calChip == 1 ? 9341 : c.calChip == 2 ? 8230 : 0);
    f.print(F("\r\n# Touch calibration (set by the display; delete this line to recalibrate)\r\n"));
    f.print(F("touch_cal = ")); f.print(buf); f.print(F("\r\n"));
  }
}

// ---------------------------------------------------------------- built-in memory (EEPROM)
#define EE_MAGIC 0x544E4853UL   // "SHNT"
struct EEBlob { uint32_t magic; uint16_t size; Config c; uint16_t sum; };
struct EEBlobV1 { uint32_t magic; uint16_t size; ConfigV1 c; uint16_t sum; };   // saved by earlier versions

static uint16_t eeSum(const void *data, size_t n) {
  const uint8_t *p = (const uint8_t *)data;
  uint16_t s = 0x5A5A;
  for (size_t i = 0; i < n; i++) s = (uint16_t)((s << 1) | (s >> 15)) ^ p[i];
  return s;
}
static uint16_t eeSum(const Config &c) { return eeSum(&c, sizeof(Config)); }
static bool eepromLoad(Config &c) {
  EEBlob b;
  EEPROM.get(0, b);
  if (b.magic == EE_MAGIC && b.size == sizeof(Config) && b.sum == eeSum(b.c)) {
    c = b.c;
  } else {
    // settings saved before the extra chargers: keep them (the charger slots start empty)
    EEBlobV1 v1;
    EEPROM.get(0, v1);
    if (v1.magic != EE_MAGIC || v1.size != sizeof(ConfigV1) || v1.sum != eeSum(&v1.c, sizeof(ConfigV1))) return false;
    c = Config();
    (ConfigV1 &)c = v1.c;
  }
  c.mac[17] = 0; c.key[32] = 0;
  for (int i = 0; i < CHARGER_SLOTS; i++) { c.chMac[i][17] = 0; c.chKey[i][32] = 0; }
  if (c.otherSource >= N_SOURCES) c.otherSource = SRC_AUTO;
  if (c.loadsIcon >= N_LOADS_ICONS) c.loadsIcon = 0;
  return true;
}
static bool eepromSave(const Config &c) {
  EEBlob b;
  memset(&b, 0, sizeof(b));
  b.magic = EE_MAGIC; b.size = sizeof(Config); b.c = c; b.sum = eeSum(b.c);
  EEPROM.put(0, b);                       // only bytes that changed are rewritten
  EEBlob check;
  EEPROM.get(0, check);
  return memcmp(&check, &b, sizeof(b)) == 0;
}

// ---------------------------------------------------------------- SD card
static bool sdWriteConfig(const Config &c) {
  pinMode(SD_CS_PIN, OUTPUT);
  digitalWrite(SD_CS_PIN, HIGH);
  if (!SD.begin(SD_CS_PIN)) return false;
  SD.remove(CONFIG_FILE);                 // FILE_WRITE appends, so start fresh
  File f = SD.open(CONFIG_FILE, FILE_WRITE);
  if (!f) { SD.end(); return false; }
  cfgWrite(f, c);
  f.close();
  SD.end();
  return true;
}

// Saves to the built-in memory, and to the SD card if there is one.
enum { SAVED_SD = 1, SAVED_MEMORY = 2 };
static int saveConfig(const Config &c) {
  int r = 0;
  if (eepromSave(c)) r |= SAVED_MEMORY;
  if (sdWriteConfig(c)) r |= SAVED_SD;
  return r;
}

// Loads settings into `c`. `badLines` counts CONFIG.TXT lines that couldn't be understood.
// Priority: CONFIG.TXT on the card, then the built-in memory, then the defaults.
static ConfigSource loadConfig(Config &c, int &badLines) {
  badLines = 0;
  bool inMemory = eepromLoad(c);          // c = saved settings, or stays at the defaults

  pinMode(SD_CS_PIN, OUTPUT);
  digitalWrite(SD_CS_PIN, HIGH);
  if (!SD.begin(SD_CS_PIN)) return inMemory ? CFG_FROM_MEMORY : CFG_NO_CARD;

  if (!SD.exists(CONFIG_FILE)) {           // blank card: give it a CONFIG.TXT
    SD.end();
    bool written = sdWriteConfig(c);
    if (inMemory) return written ? CFG_MEMORY_TO_SD : CFG_FROM_MEMORY;
    return written ? CFG_TEMPLATE_WRITTEN : CFG_NO_FILE;
  }

  File f = SD.open(CONFIG_FILE, FILE_READ);
  if (!f) { SD.end(); return inMemory ? CFG_FROM_MEMORY : CFG_NO_FILE; }
  Config fromFile;                        // the file is the full truth: start from defaults
  char line[96];
  int len = 0;
  while (true) {
    int ch = f.read();
    if (ch == '\n' || ch < 0) {
      line[len] = 0;
      if (!cfgLine(fromFile, line)) badLines++;
      len = 0;
      if (ch < 0) break;
    } else if (len < (int)sizeof(line) - 1) {
      line[len++] = (char)ch;
    }
  }
  f.close();
  SD.end();
  c = fromFile;
  eepromSave(c);                          // keep the built-in copy in step with the card
  return CFG_FROM_SD;
}

// True if the MAC/key are still the example values.
static bool configIsPlaceholder(const Config &c) {
  return !strcasecmp(c.mac, PLACEHOLDER_MAC) || !strcmp(c.key, PLACEHOLDER_KEY);
}
