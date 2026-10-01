"""Translations: the Android app's strings (lang/*.json) plus the Pi's own, with plural rules,
Android-style "%1$s" placeholders and fonts that can show each language's script."""
import json
import os
import re
import shutil
import subprocess

_DIR = os.path.join(os.path.dirname(__file__), "lang")
_FMT = re.compile(r"%(?:(\d+)\$)?([-#+ 0,(]*)(\d*)(?:\.(\d+))?([sdfxX%])")

# Languages that write 12,66 rather than 12.66 (CLDR)
_DECIMAL_COMMA = {"de", "fr", "es", "pt", "it", "nl", "pl", "ru", "uk", "cs", "sk", "sl", "hr", "sr",
                  "bg", "ro", "hu", "da", "nb", "sv", "fi", "et", "lv", "lt", "el", "tr", "ca", "id",
                  "vi", "ka", "hy"}


def fmt(template, *args):
    """Formats Android-style placeholders: %1$s, %2$02d, %d, %%."""
    seq = iter(range(len(args)))

    def rep(m):
        pos, flags, width, prec, conv = m.groups()
        if conv == "%":
            return "%"
        i = int(pos) - 1 if pos else next(seq)
        spec = "%" + flags + width + ("." + prec if prec else "") + conv
        try:
            return spec % args[i]
        except (IndexError, TypeError, ValueError):
            return m.group(0)
    return _FMT.sub(rep, template)


def plural_category(lang, n):
    """CLDR cardinal plural category for a whole number."""
    base = lang.split("-")[0]
    n = abs(int(n))
    m10, m100 = n % 10, n % 100
    if base in ("ja", "ko", "zh", "vi", "th", "id", "ms"):
        return "other"
    if base in ("fr", "pt", "hi", "bn"):
        return "one" if n in (0, 1) else "other"
    if base in ("ru", "uk"):
        if m10 == 1 and m100 != 11: return "one"
        if 2 <= m10 <= 4 and not 12 <= m100 <= 14: return "few"
        return "many"
    if base == "pl":
        if n == 1: return "one"
        if 2 <= m10 <= 4 and not 12 <= m100 <= 14: return "few"
        return "many"
    if base in ("cs", "sk"):
        return "one" if n == 1 else "few" if 2 <= n <= 4 else "other"
    if base in ("hr", "sr"):
        if m10 == 1 and m100 != 11: return "one"
        if 2 <= m10 <= 4 and not 12 <= m100 <= 14: return "few"
        return "other"
    if base == "lt":
        if m10 == 1 and not 11 <= m100 <= 19: return "one"
        if m10 >= 2 and not 11 <= m100 <= 19: return "few"
        return "other"
    if base == "lv":
        if m10 == 0 or 11 <= m100 <= 19: return "zero"
        if m10 == 1 and m100 != 11: return "one"
        return "other"
    if base == "ro":
        if n == 1: return "one"
        if n == 0 or 1 <= m100 <= 19: return "few"
        return "other"
    if base == "sl":
        return {1: "one", 2: "two", 3: "few", 4: "few"}.get(m100, "other")
    if base == "fil":
        return "one" if n in (1, 2, 3) or m10 not in (4, 6, 9) else "other"
    return "one" if n == 1 else "other"


def available():
    """(tags, native names) in picker order, from the Android app's language list."""
    with open(os.path.join(_DIR, "en.json"), encoding="utf-8") as f:
        en = json.load(f)
    return en["language_tags"], en["language_names"]


def match_tag(wanted, tags=None):
    """Matches a locale ("de_DE.UTF-8", "zh-Hant", "nb_NO", "in") to one of our tags, or None."""
    if not wanted:
        return None
    tags = tags or available()[0]
    w = wanted.split(".")[0].split("@")[0].replace("_", "-")
    if w in ("C", "POSIX"):
        return None
    for t in tags:
        if t.lower() == w.lower():
            return t
    parts = w.split("-")
    lang = parts[0].lower()
    lang = {"in": "id", "no": "nb", "nn": "nb", "tl": "fil", "iw": "he"}.get(lang, lang)
    if lang == "zh":
        rest = [p.lower() for p in parts[1:]]
        return "zh-TW" if any(p in ("hant", "tw", "hk", "mo") for p in rest) else "zh-CN"
    return lang if lang in tags else None


def system_language():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        t = match_tag(os.environ.get(var, ""))
        if t:
            return t
    return "en"


class Strings:
    def __init__(self, tag):
        self.tag = tag if tag in available()[0] else "en"
        with open(os.path.join(_DIR, "en.json"), encoding="utf-8") as f:
            self._d = json.load(f)
        if self.tag != "en":
            with open(os.path.join(_DIR, self.tag + ".json"), encoding="utf-8") as f:
                self._d.update(json.load(f))
        self.decimal_comma = self.tag.split("-")[0] in _DECIMAL_COMMA

    def __call__(self, key, *args):
        return fmt(self._d.get(key, key), *args)

    def array(self, key):
        return self._d.get(key, [])

    def plural(self, key, n, *args):
        forms = self._d.get(key, {})
        text = forms.get(plural_category(self.tag, n)) or forms.get("other") or key
        return fmt(text, n, *args)


# ------------------------------------------------------------------ fonts

_font_cache = {}


def font_files(tag):
    """(regular, bold) font files that can show this language's script, via fontconfig."""
    if tag in _font_cache:
        return _font_cache[tag]
    lang = tag.lower()
    result = (None, None)
    if shutil.which("fc-match"):
        def match(weight):
            try:
                out = subprocess.run(["fc-match", "-f", "%{file}", "sans-serif:lang=%s:weight=%s" % (lang, weight)],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                return out if out and os.path.exists(out) else None
            except (OSError, subprocess.SubprocessError):
                return None
        result = (match("regular"), match("bold"))
    _font_cache[tag] = result
    return result


def fallback_font_files():
    """DejaVu Sans: Latin, Greek, Cyrillic, Georgian, Armenian and symbols such as ⚙ and →."""
    for reg, bold in (("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),):
        if os.path.exists(reg):
            return reg, bold if os.path.exists(bold) else reg
    return font_files("en")
