"""Settings, stored in a CONFIG.TXT-style text file.

Same "name = value" format as the Arduino display's SD card and the Android app's export, so
the files can be shared. Settings only the Arduino uses (rotation, lcd_chip, invert, touch_cal)
are kept as they are, so a round trip doesn't lose them.
"""
import copy
import os

from .victron import normalise_key, normalise_mac

THEME_LIGHT, THEME_DARK = 1, 2          # same numbers as the Android app (0 = follow the phone)
ROTATIONS = (0, 90, 180, 270)
SCREEN_OFF_CHOICES = (0, 30, 60, 120, 300, 600, 1800, 3600)   # seconds; 0 = never
CHARGER_SLOTS = 2
# What to call charging the extra chargers don't account for ("auto": Charger, or Other once a
# charger has been added)
OTHER_SOURCES = ("auto", "dcdc", "solar", "mains", "alternator")
LOADS_ICONS = ("house", "caravan", "boat")    # the picture on the Loads node

_ARDUINO_ONLY = ("rotation", "lcd_chip", "invert", "touch_cal")


class Settings:
    def __init__(self):
        # Shared with the Arduino display and the Android app
        self.mac = ""                # "aa:bb:cc:dd:ee:ff" or ""
        self.key = ""                # 32 lower-case hex digits or ""
        self.demo = False
        self.stale_after = 30
        self.soc_amber = 50
        self.soc_red = 20
        self.screen_off = 0          # seconds without a touch before the screen turns off; 0 = never
        # Extra Victron chargers (Blue Smart IP22, SmartSolar MPPT, Orion XS): MAC and key per slot
        self.charger_mac = [""] * CHARGER_SLOTS
        self.charger_key = [""] * CHARGER_SLOTS
        self.other_source = "auto"
        self.loads_icon = "house"
        # Raspberry Pi only
        self.theme = THEME_DARK
        self.language = ""           # "" = the system language
        self.screen_rotation = 0     # degrees
        self.brightness = 100        # percent, if the screen's backlight can be controlled
        # Arduino-only lines, kept for writing back
        self.passthrough = []

    def copy(self):
        return copy.deepcopy(self)

    def needs_setup(self):
        return (not self.mac or not self.key or self.mac == "aa:bb:cc:dd:ee:ff"
                or self.key == "0123456789abcdef0123456789abcdef")

    def chargers(self):
        """The charger slots in use: [(slot, mac, key)]."""
        return [(i, m, k) for i, (m, k) in enumerate(zip(self.charger_mac, self.charger_key)) if m and k]

    def __eq__(self, other):
        return isinstance(other, Settings) and vars(self) == vars(other)

    # -------------------------------------------------------------- parsing

    def _apply(self, name, val, line):
        name = name.lower()
        try:
            n = int(val.strip())
        except ValueError:
            n = None
        if name == "mac":
            m = normalise_mac(val)
            if m is None: return False
            self.mac = m
        elif name == "key":
            k = normalise_key(val)
            if k is None: return False
            self.key = k
        elif (len(name) == 12 and name.startswith("charger") and name[7].isdigit()
              and name[8:] in ("_mac", "_key") and 1 <= int(name[7]) <= CHARGER_SLOTS):
            i = int(name[7]) - 1
            if name.endswith("_mac"):
                m = normalise_mac(val) if val.strip() else ""
                if m is None: return False
                self.charger_mac[i] = m
            else:
                k = normalise_key(val) if val.strip() else ""
                if k is None: return False
                self.charger_key[i] = k
        elif name == "other_source":
            v = val.strip().lower()
            if v not in OTHER_SOURCES: return False
            self.other_source = v
        elif name == "loads_icon":
            v = val.strip().lower()
            if v not in LOADS_ICONS: return False
            self.loads_icon = v
        elif name == "demo":
            if n is None: return False
            self.demo = n != 0
        elif name == "stale_after":
            if n is None or n < 2: return False
            self.stale_after = n
        elif name in ("soc_amber", "soc_red"):
            if n is None: return False
            setattr(self, name, max(0, min(100, n)))
        elif name == "screen_off":
            if n is None or n < 0: return False
            self.screen_off = n
        elif name == "theme":
            if n is None or n < 0 or n > 2: return False
            self.theme = THEME_LIGHT if n == THEME_LIGHT else THEME_DARK
        elif name == "language":
            self.language = val.strip()
        elif name == "screen_rotation":
            if n not in ROTATIONS: return False
            self.screen_rotation = n
        elif name == "brightness":
            if n is None: return False
            self.brightness = max(10, min(100, n))
        elif name in _ARDUINO_ONLY:
            self.passthrough = [l for l in self.passthrough if l.split("=")[0].strip().lower() != name]
            self.passthrough.append(line.strip())
        elif name in ("keep_awake", "full_screen", "orientation"):
            pass                     # Android-only settings: ignored, not an error
        else:
            return False
        return True

    def import_text(self, text):
        """Reads CONFIG.TXT text on top of these settings. Returns (settings, bad_line_count)."""
        s = self.copy()
        bad = 0
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                bad += 1
                continue
            name, val = line.split("=", 1)
            if not s._apply(name.strip(), val.strip(), line):
                bad += 1
        return s, bad

    def export_text(self):
        nl = "\n"
        out = [
            "# SmartShunt display settings (Raspberry Pi)",
            "# Lines starting with # are ignored. The display reads this file when it starts.",
            "",
            "# From VictronConnect: SmartShunt > settings > ... > Product info >",
            "# Instant readout via Bluetooth > Show",
        ]
        if self.mac: out.append("mac = " + self.mac)
        if self.key: out.append("key = " + self.key)
        out += [
            "", "# Extra Victron chargers (optional): Blue Smart IP22, SmartSolar MPPT or Orion XS,",
            "# with Instant readout turned on. MAC and key from VictronConnect, as for the shunt.",
        ]
        for i in range(CHARGER_SLOTS):
            if self.charger_mac[i] or self.charger_key[i]:
                out += ["charger%d_mac = %s" % (i + 1, self.charger_mac[i]),
                        "charger%d_key = %s" % (i + 1, self.charger_key[i])]
        out += [
            "# Name for charging they don't account for: auto, dcdc, solar, mains or alternator",
            "other_source = " + self.other_source,
            "", "# Picture on the Loads node: house, caravan or boat",
            "loads_icon = " + self.loads_icon,
            "", "# 1 = show fake data (to test the screen), 0 = read the shunt",
            "demo = %d" % (1 if self.demo else 0),
            "", "# Seconds without data before showing 'No signal'",
            "stale_after = %d" % self.stale_after,
            "# State of charge colours: amber below this %, red below the next",
            "soc_amber = %d" % self.soc_amber,
            "soc_red = %d" % self.soc_red,
            "", "# Seconds without a touch before the screen turns off (a tap wakes it). 0 = never",
            "screen_off = %d" % self.screen_off,
            "", "# Raspberry Pi only",
            "# theme: 2 = dark, 1 = light",
            "theme = %d" % self.theme,
            "# language: blank = the system language, or a code such as de, fr, ja, zh-TW",
            "language = " + self.language,
            "# screen_rotation: 0, 90, 180 or 270 degrees",
            "screen_rotation = %d" % self.screen_rotation,
            "# brightness: 10-100 %, if the screen's backlight can be controlled",
            "brightness = %d" % self.brightness,
        ]
        if self.passthrough:
            out += ["", "# Arduino display only (kept from an imported file)"] + self.passthrough
        return nl.join(out) + nl


# ------------------------------------------------------------------ where the file lives

def default_path():
    """The boot partition when running as root (so it can be edited on a PC, like the
    Arduino display's SD card), otherwise the user's config folder."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        for boot in ("/boot/firmware", "/boot"):
            if os.path.isdir(boot) and os.access(boot, os.W_OK):
                return os.path.join(boot, "shunt-display.txt")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "shunt-display", "CONFIG.TXT")


def load(path):
    """Returns (settings, bad_line_count, existed)."""
    s = Settings()
    # utf-8-sig: Windows editors may add a byte-order mark. If power was lost while saving,
    # only the temporary file may be left: use it.
    for candidate in (path, path + ".tmp"):
        try:
            with open(candidate, encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
            break
        except FileNotFoundError:
            continue
    else:
        return s, 0, False
    s, bad = s.import_text(text)
    return s, bad, True


def save(settings, path):
    """Writes the file safely: a temporary file, flushed to disk, then renamed over the old one
    (the Pi may lose power at any time)."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(settings.export_text())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        fd = os.open(folder or ".", os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except OSError:
        pass
