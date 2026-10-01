// Victron "Instant Readout" decoder for battery monitors (SmartShunt / BMV) and chargers
// (Blue Smart IP22, SmartSolar MPPT, Orion XS).
// Self-contained: includes a small AES-128 (encrypt-only, which is all CTR mode needs).
#pragma once
#include <stdint.h>
#include <string.h>
#include <math.h>

// ------------------------------------------------------------ AES-128 (encrypt only)
namespace aes128 {
static const uint8_t SBOX[256] = {
  0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
  0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
  0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
  0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
  0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
  0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
  0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
  0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
  0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
  0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
  0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
  0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
  0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
  0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
  0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
  0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16};

static inline uint8_t xt(uint8_t x) { return (uint8_t)((x << 1) ^ ((x & 0x80) ? 0x1b : 0)); }

// Encrypt one 16-byte block in place with a 16-byte key.
static void encryptBlock(const uint8_t key[16], uint8_t s[16]) {
  uint8_t rk[16];
  memcpy(rk, key, 16);
  uint8_t rcon = 1;
  for (int i = 0; i < 16; i++) s[i] ^= rk[i];
  for (int round = 1; round <= 10; round++) {
    // SubBytes + ShiftRows
    uint8_t t[16];
    for (int c = 0; c < 4; c++)
      for (int r = 0; r < 4; r++)
        t[c * 4 + r] = SBOX[s[((c + r) & 3) * 4 + r]];
    // MixColumns (not in last round)
    if (round < 10) {
      for (int c = 0; c < 4; c++) {
        uint8_t *a = &t[c * 4];
        uint8_t a0 = a[0], a1 = a[1], a2 = a[2], a3 = a[3], all = a0 ^ a1 ^ a2 ^ a3;
        a[0] ^= all ^ xt(a0 ^ a1);
        a[1] ^= all ^ xt(a1 ^ a2);
        a[2] ^= all ^ xt(a2 ^ a3);
        a[3] ^= all ^ xt(a3 ^ a0);
      }
    }
    // next round key
    uint8_t k0 = SBOX[rk[13]] ^ rcon, k1 = SBOX[rk[14]], k2 = SBOX[rk[15]], k3 = SBOX[rk[12]];
    rk[0] ^= k0; rk[1] ^= k1; rk[2] ^= k2; rk[3] ^= k3;
    for (int i = 4; i < 16; i++) rk[i] ^= rk[i - 4];
    rcon = xt(rcon);
    for (int i = 0; i < 16; i++) s[i] = t[i] ^ rk[i];
  }
}
}  // namespace aes128

// ------------------------------------------------------------ Victron decoding
struct ShuntReading {
  bool  valid = false;
  float voltage = NAN;       // V
  float current = NAN;       // A (+ charging, - discharging)
  float soc = NAN;           // %
  float consumedAh = NAN;    // Ah (negative)
  int32_t remainingMins = -1;  // -1 = not available
  uint16_t alarm = 0;
  uint8_t auxMode = 3;       // 0 starter V, 1 midpoint V, 2 temperature, 3 none
  float aux = NAN;           // starter/midpoint V or temperature in °C
  uint16_t modelId = 0;      // e.g. 0xA389 = SmartShunt 500A/50mV
};

enum VictronResult { VIC_OK, VIC_NOT_VICTRON, VIC_NOT_BATTERY_MONITOR, VIC_NOT_CHARGER, VIC_BAD_KEY };

// A Victron charger's reading. kind: 0 mains (AC charger), 1 solar (MPPT), 2 DC-DC (Orion XS)
enum { CHG_MAINS = 0, CHG_SOLAR = 1, CHG_DCDC = 2 };
struct ChargerReading {
  bool  valid = false;
  uint8_t kind = CHG_MAINS;
  int16_t state = -1;        // Victron operation mode: 0 off, 3 bulk, 4 absorption, 5 float...
  int16_t error = -1;        // charger error code, 0 = none
  float voltage = NAN;       // V (output 1)
  float current = NAN;       // A (all outputs)
  float power = NAN;         // W out to the batteries
};

// Charger kind for a record type (byte 4), or -1 if it isn't a charger.
static int victronChargerKind(uint8_t rec) {
  return rec == 0x08 ? CHG_MAINS : rec == 0x01 ? CHG_SOLAR : rec == 0x0F ? CHG_DCDC : -1;
}

// Convert "0123abcd..." (32 hex chars) to 16 bytes. Returns false if malformed.
static bool victronParseKey(const char *hex, uint8_t key[16]) {
  auto nib = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  for (int i = 0; i < 16; i++) {
    int h = nib(hex[i * 2]), l = h < 0 ? -1 : nib(hex[i * 2 + 1]);
    if (h < 0 || l < 0) return false;
    key[i] = (uint8_t)(h << 4 | l);
  }
  return hex[32] == 0;
}

// Read `bits` bits LSB-first from buf starting at bit position *pos.
static uint32_t vicBits(const uint8_t *buf, int *pos, int bits) {
  uint32_t v = 0;
  for (int i = 0; i < bits; i++, (*pos)++)
    v |= (uint32_t)((buf[*pos >> 3] >> (*pos & 7)) & 1) << i;
  return v;
}
static int32_t vicSigned(uint32_t v, int bits) {
  return (v & (1UL << (bits - 1))) ? (int32_t)(v - (1UL << bits)) : (int32_t)v;
}

// AES-CTR payload of an advertisement (128-bit little-endian counter starting at the IV).
static void victronDecrypt(const uint8_t *d, int len, const uint8_t key[16], uint8_t plain[32]) {
  const uint16_t iv = d[5] | (d[6] << 8);
  memset(plain, 0, 32);
  int n = len - 8;
  if (n > 32) n = 32;
  for (int off = 0; off < n; off += 16) {
    uint8_t block[16] = {0};
    uint32_t ctr = iv + off / 16;
    block[0] = ctr & 0xff; block[1] = (ctr >> 8) & 0xff; block[2] = (ctr >> 16) & 0xff;
    aes128::encryptBlock(key, block);
    for (int i = 0; i < 16 && off + i < n; i++) plain[off + i] = d[8 + off + i] ^ block[i];
  }
}

// Charger record layouts from Victron's "extra manufacturer data" document (Orion XS: as decoded
// by the victron-ble and esphome-victron_ble projects).
static void victronDecodeChargerPlain(uint8_t rec, const uint8_t *plain, ChargerReading &out) {
  int p = 0;
  out = ChargerReading();
  out.valid = true;
  out.kind = victronChargerKind(rec);
  uint32_t state = vicBits(plain, &p, 8), error = vicBits(plain, &p, 8);
  out.state = state == 0xFF ? -1 : (int16_t)state;
  out.error = error == 0xFF ? -1 : (int16_t)error;
  if (rec == 0x08) {                      // up to 3 outputs: 13-bit V (0.01) and 11-bit A (0.1)
    float watts = 0, amps = 0;
    bool any = false;
    for (int i = 0; i < 3; i++) {
      uint32_t v = vicBits(plain, &p, 13), a = vicBits(plain, &p, 11);
      if (v == 0x1FFF || a == 0x7FF) continue;
      if (i == 0) out.voltage = v / 100.0f;
      watts += v / 100.0f * (a / 10.0f);
      amps += a / 10.0f;
      any = true;
    }
    if (any) { out.current = amps; out.power = watts; }
  } else if (rec == 0x01) {               // solar: V, A (signed), yield, PV watts
    uint32_t v = vicBits(plain, &p, 16), a = vicBits(plain, &p, 16);
    vicBits(plain, &p, 16);
    uint32_t pv = vicBits(plain, &p, 16);
    out.voltage = v == 0x7FFF ? NAN : vicSigned(v, 16) / 100.0f;
    out.current = a == 0x7FFF ? NAN : vicSigned(a, 16) / 10.0f;
    if (!isnan(out.voltage) && !isnan(out.current)) out.power = out.voltage * out.current;
    else if (pv != 0xFFFF) out.power = pv;
  } else if (rec == 0x0F) {               // Orion XS: output V, output A
    uint32_t v = vicBits(plain, &p, 16), a = vicBits(plain, &p, 16);
    out.voltage = v == 0xFFFF ? NAN : v / 100.0f;
    out.current = a == 0xFFFF ? NAN : a / 10.0f;
    if (!isnan(out.voltage) && !isnan(out.current)) out.power = out.voltage * out.current;
  }
}

static VictronResult victronDecodeCharger(const uint8_t *d, int len, const uint8_t key[16], ChargerReading &out) {
  if (len < 9 || d[0] != 0x10) return VIC_NOT_VICTRON;
  if (victronChargerKind(d[4]) < 0) return VIC_NOT_CHARGER;
  if (d[7] != key[0]) return VIC_BAD_KEY;
  uint8_t plain[32];
  victronDecrypt(d, len, key, plain);
  victronDecodeChargerPlain(d[4], plain, out);
  return VIC_OK;
}

// `d` is the manufacturer data AFTER the 2-byte company ID (0x02E1).
static VictronResult victronDecode(const uint8_t *d, int len, const uint8_t key[16], ShuntReading &out) {
  if (len < 9 || d[0] != 0x10) return VIC_NOT_VICTRON;
  if (d[4] != 0x02) return VIC_NOT_BATTERY_MONITOR;  // 0x02 = battery monitor record
  if (d[7] != key[0]) return VIC_BAD_KEY;
  uint8_t plain[32];
  victronDecrypt(d, len, key, plain);

  int p = 0;
  uint32_t remaining = vicBits(plain, &p, 16);
  int32_t  voltage   = vicSigned(vicBits(plain, &p, 16), 16);
  uint32_t alarm     = vicBits(plain, &p, 16);
  uint32_t aux       = vicBits(plain, &p, 16);
  uint32_t auxMode   = vicBits(plain, &p, 2);
  uint32_t currRaw   = vicBits(plain, &p, 22);
  uint32_t consumed  = vicBits(plain, &p, 20);
  uint32_t soc       = vicBits(plain, &p, 10);

  out = ShuntReading();
  out.valid = true;
  out.modelId = d[2] | (d[3] << 8);
  out.remainingMins = remaining == 0xFFFF ? -1 : (int32_t)remaining;
  out.voltage = voltage == 0x7FFF ? NAN : voltage / 100.0f;
  out.alarm = alarm;
  out.auxMode = auxMode;
  out.current = currRaw == 0x3FFFFF ? NAN : vicSigned(currRaw, 22) / 1000.0f;
  out.consumedAh = consumed == 0xFFFFF ? NAN : -(float)consumed / 10.0f;
  out.soc = soc == 0x3FF ? NAN : soc / 10.0f;
  if (auxMode == 0) out.aux = vicSigned(aux, 16) / 100.0f;           // starter V
  else if (auxMode == 1) out.aux = aux / 100.0f;                      // midpoint V
  else if (auxMode == 2) out.aux = aux / 100.0f - 273.15f;            // K -> °C
  return VIC_OK;
}
