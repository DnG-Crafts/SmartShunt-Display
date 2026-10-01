"""Victron "Instant Readout" decoder for battery monitors (SmartShunt, BMV-71x) and chargers
(Blue Smart IP22, SmartSolar MPPT, Orion XS).

Same format and rules as the Arduino (victron.h) and Android (VictronDecoder.java) versions.

Manufacturer data under company ID 0x02E1 (bleak gives it without the company ID):
  [0..1] record prefix   [2..3] model ID (LE)   [4] record type (0x02 = battery monitor)
  [5..6] IV / counter (LE)   [7] first byte of the key   [8..] AES-128-CTR payload
"""
import math

VICTRON_COMPANY_ID = 0x02E1

AUX_STARTER, AUX_MIDPOINT, AUX_TEMPERATURE, AUX_NONE = 0, 1, 2, 3

OK, NOT_VICTRON, NOT_BATTERY_MONITOR, BAD_KEY = "ok", "not_victron", "not_battery_monitor", "bad_key"


class Reading:
    """One decoded reading. NaN / -1 mean "not available"."""
    __slots__ = ("voltage", "current", "soc", "consumed_ah", "remaining_mins", "alarm",
                 "aux_mode", "aux", "model_id")

    def __init__(self):
        self.voltage = self.current = self.soc = self.consumed_ah = self.aux = math.nan
        self.remaining_mins = -1
        self.alarm = 0
        self.aux_mode = AUX_NONE
        self.model_id = 0

    @property
    def power(self):
        return self.voltage * self.current


# ------------------------------------------------------------------ AES-128 (encrypt only)
# A small table-driven AES so the decoder has no dependencies. It only runs once a second.

def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]


def _expand_key(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def aes128_encrypt_block(round_keys, block):
    s = [b ^ k for b, k in zip(block, round_keys[0])]
    for rnd in range(1, 11):
        s = [_SBOX[b] for b in s]
        # ShiftRows (state is column-major: s[c*4 + r])
        s = [s[((c + r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        if rnd != 10:
            m = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                m += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = m
        s = [b ^ k for b, k in zip(s, round_keys[rnd])]
    return bytes(s)


# ------------------------------------------------------------------ helpers

def hex_only(val, want):
    """Keeps hex digits (ignoring : - space .), lower-cased. None if anything else, or the wrong count."""
    if val is None:
        return None
    out = []
    for c in val:
        if c in ":- .":
            continue
        if c not in "0123456789abcdefABCDEF" or len(out) >= want:
            return None
        out.append(c.lower())
    return "".join(out) if len(out) == want else None


def normalise_mac(val):
    h = hex_only(val, 12)
    return None if h is None else ":".join(h[i:i + 2] for i in range(0, 12, 2))


def normalise_key(val):
    return hex_only(val, 32)


def parse_key(val):
    h = normalise_key(val)
    return None if h is None else bytes.fromhex(h)


def model_id(d):
    return d[2] | (d[3] << 8) if d is not None and len(d) >= 4 else 0


def is_battery_monitor(d):
    return d is not None and len(d) >= 9 and d[0] == 0x10 and d[4] == 0x02


_key_cache = {}

# Charger record types (byte 4), and what the dashboard calls them
REC_SOLAR, REC_BATTERY, REC_AC_CHARGER, REC_ORION_XS = 0x01, 0x02, 0x08, 0x0F
CHARGER_KINDS = {REC_AC_CHARGER: "mains", REC_SOLAR: "solar", REC_ORION_XS: "dcdc"}


def record_type(d):
    return d[4] if d is not None and len(d) >= 9 and d[0] == 0x10 else -1


def is_charger(d):
    return record_type(d) in CHARGER_KINDS


def _decrypt(d, key):
    """AES-128-CTR payload, or None if the key's first byte doesn't match."""
    if key is None or len(key) != 16 or d[7] != key[0]:
        return None
    rk = _key_cache.get(key)
    if rk is None:
        if len(_key_cache) > 8:
            _key_cache.clear()
        rk = _key_cache[key] = _expand_key(key)
    iv = d[5] | (d[6] << 8)
    payload = d[8:8 + 32]
    plain = bytearray(32)
    for off in range(0, len(payload), 16):
        ctr = iv + off // 16          # 128-bit little-endian counter
        ks = aes128_encrypt_block(rk, ctr.to_bytes(16, "little"))
        for i in range(min(16, len(payload) - off)):
            plain[off + i] = payload[off + i] ^ ks[i]
    return bytes(plain)


def decode(d, key):
    """Decodes manufacturer data (without the company ID). Returns (result, Reading or None)."""
    if d is None or len(d) < 9 or d[0] != 0x10:
        return NOT_VICTRON, None
    if d[4] != REC_BATTERY:
        return NOT_BATTERY_MONITOR, None
    plain = _decrypt(d, key)
    if plain is None:
        return BAD_KEY, None
    r = decode_plain(plain)
    r.model_id = model_id(d)
    return OK, r


class ChargerReading:
    """A Victron charger's Instant Readout. NaN / -1 mean "not available".
    kind: "mains" (Blue Smart IP22 and other AC chargers), "solar" (MPPT) or "dcdc" (Orion XS)."""
    __slots__ = ("kind", "state", "error", "voltage", "current", "power", "model_id")

    def __init__(self, kind=""):
        self.kind = kind
        self.state = self.error = -1
        self.voltage = self.current = self.power = math.nan
        self.model_id = 0


NOT_CHARGER = "not_charger"


def decode_charger(d, key):
    """Decodes a charger's manufacturer data. Returns (result, ChargerReading or None)."""
    if d is None or len(d) < 9 or d[0] != 0x10:
        return NOT_VICTRON, None
    kind = CHARGER_KINDS.get(d[4])
    if kind is None:
        return NOT_CHARGER, None
    plain = _decrypt(d, key)
    if plain is None:
        return BAD_KEY, None
    r = decode_charger_plain(d[4], plain)
    r.model_id = model_id(d)
    return OK, r


def _bit_reader(plain):
    n = int.from_bytes(plain, "little")
    pos = [0]

    def bits(count):
        v = (n >> pos[0]) & ((1 << count) - 1)
        pos[0] += count
        return v
    return bits


def decode_charger_plain(rec, plain):
    """Record layouts from Victron's "extra manufacturer data" document (Orion XS: as decoded by
    the victron-ble and esphome-victron_ble projects). Power is what goes out to the batteries."""
    bits = _bit_reader(plain)
    r = ChargerReading(CHARGER_KINDS.get(rec, ""))
    state, error = bits(8), bits(8)
    r.state = -1 if state == 0xFF else state
    r.error = -1 if error == 0xFF else error
    if rec == REC_AC_CHARGER:
        # up to three outputs: 13-bit volts (0.01 V) and 11-bit amps (0.1 A) each
        total, amps, any_ = 0.0, 0.0, False
        for i in range(3):
            v, a = bits(13), bits(11)
            if v == 0x1FFF or a == 0x7FF:
                continue
            if i == 0:
                r.voltage = v / 100
            total += v / 100 * a / 10
            amps += a / 10
            any_ = True
        if any_:
            r.current, r.power = amps, total
    elif rec == REC_SOLAR:
        v, a = bits(16), bits(16)
        bits(16)                                   # yield today
        pv = bits(16)
        r.voltage = math.nan if v == 0x7FFF else _signed(v, 16) / 100
        r.current = math.nan if a == 0x7FFF else _signed(a, 16) / 10
        if not math.isnan(r.voltage) and not math.isnan(r.current):
            r.power = r.voltage * r.current
        elif pv != 0xFFFF:
            r.power = float(pv)
    elif rec == REC_ORION_XS:
        v, a = bits(16), bits(16)
        r.voltage = math.nan if v == 0xFFFF else v / 100
        r.current = math.nan if a == 0xFFFF else a / 10
        if not math.isnan(r.voltage) and not math.isnan(r.current):
            r.power = r.voltage * r.current
    return r


def _signed(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def decode_plain(plain):
    """Decodes a decrypted battery-monitor payload (little-endian bit fields)."""
    n = int.from_bytes(plain, "little")
    pos = 0

    def bits(count):
        nonlocal pos
        v = (n >> pos) & ((1 << count) - 1)
        pos += count
        return v

    remaining = bits(16); voltage = _signed(bits(16), 16); alarm = bits(16); aux = bits(16)
    aux_mode = bits(2); current = bits(22); consumed = bits(20); soc = bits(10)
    r = Reading()
    r.remaining_mins = -1 if remaining == 0xFFFF else remaining
    r.voltage = math.nan if voltage == 0x7FFF else voltage / 100
    r.alarm = alarm
    r.aux_mode = aux_mode
    r.current = math.nan if current == 0x3FFFFF else _signed(current, 22) / 1000
    r.consumed_ah = math.nan if consumed == 0xFFFFF else -consumed / 10
    r.soc = math.nan if soc == 0x3FF else soc / 10
    if aux_mode == AUX_STARTER:
        r.aux = _signed(aux, 16) / 100
    elif aux_mode == AUX_MIDPOINT:
        r.aux = aux / 100
    elif aux_mode == AUX_TEMPERATURE:
        r.aux = aux / 100 - 273.15
    return r


_MODELS = {
    0xA380: "BMV-710 Smart", 0xA381: "BMV-712 Smart", 0xA383: "BMV-712 Smart", 0xA382: "BMV-710H Smart",
    0xA389: "SmartShunt 500A/50mV", 0xA38A: "SmartShunt 1000A/50mV", 0xA38B: "SmartShunt 2000A/50mV",
    0xA38C: "SmartShunt IP67 500A/50mV", 0xA38D: "SmartShunt IP67 1000A/50mV",
    0xA38E: "SmartShunt IP67 2000A/50mV",
    0xC030: "SmartShunt IP65 500A/50mV", 0xC035: "SmartShunt IP65 500A/50mV",
    0xC031: "SmartShunt IP65 1000A/50mV", 0xC036: "SmartShunt IP65 1000A/50mV",
    0xC032: "SmartShunt IP65 2000A/50mV", 0xC037: "SmartShunt IP65 2000A/50mV",
    0xC038: "SmartShunt 300A/50mV",
}


def model_name(mid):
    return _MODELS.get(mid)
