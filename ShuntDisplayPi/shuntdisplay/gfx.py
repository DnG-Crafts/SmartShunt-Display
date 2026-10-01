"""Drawing helpers: themes, text with per-character font fallback, anti-aliased rounded shapes."""
import pygame
import pygame.freetype
import pygame.gfxdraw

from . import i18n

DARK = dict(bg=(0x0E, 0x11, 0x16), panel=(0x1C, 0x21, 0x2A), track=(0x0E, 0x11, 0x16),
            text=(0xEB, 0xEE, 0xF3), muted=(0x8C, 0x96, 0xA5), good=(0x3C, 0xC8, 0x78),
            warn=(0xF0, 0xB4, 0x32), bad=(0xE6, 0x46, 0x46), press=(0x2A, 0x31, 0x3C),
            line=(0x2A, 0x31, 0x3C), key=(0x26, 0x2C, 0x37),
            # energy-flow colours: fixed hues, checked for colour-blind separation on this panel colour
            # (the same as the AlphaESS display's solar, house, battery and grid)
            charger=(0xC9, 0x85, 0x00), loads=(0x39, 0x87, 0xE5), battery=(0x00, 0x83, 0x00), accent=(0xD5, 0x51, 0x81))
LIGHT = dict(bg=(0xF1, 0xF3, 0xF6), panel=(0xFF, 0xFF, 0xFF), track=(0xE3, 0xE7, 0xED),
             text=(0x14, 0x18, 0x1F), muted=(0x6B, 0x74, 0x82), good=(0x1F, 0x9D, 0x55),
             warn=(0xC2, 0x7E, 0x00), bad=(0xD8, 0x3A, 0x3A), press=(0xE3, 0xE7, 0xED),
             line=(0xE3, 0xE7, 0xED), key=(0xE9, 0xEC, 0xF1),
             charger=(0xED, 0xA1, 0x00), loads=(0x2A, 0x78, 0xD6), battery=(0x00, 0x83, 0x00), accent=(0xE8, 0x7B, 0xA4))


class Text:
    """Renders text in the language's font. Any character that font lacks (⚙ in a Thai font,
    日本語 in a Latin one, in the language list) comes from the first fallback font that has it:
    DejaVu Sans, then fonts for other scripts found through fontconfig."""

    _SCRIPT_LANGS = ("ja", "ko", "zh-cn", "zh-tw", "th", "hi", "bn", "ta", "te", "ka", "hy")

    def __init__(self, lang):
        reg, bold = i18n.font_files(lang)
        fb_reg, fb_bold = i18n.fallback_font_files()
        self.mono = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
        # font chains, regular and bold: main font first, then fallbacks (script fonts added lazily)
        self.chain = {False: [f for f in (reg or fb_reg, fb_reg) if f],
                      True: [f for f in (bold or reg or fb_bold, fb_bold) if f]}
        self._scripts_added = {False: False, True: False}
        self._fonts = {}
        self._cache = {}
        self._glyph = {}         # (file, char) -> has glyph
        self._ft = {}

    def _has(self, path, ch):
        k = (path, ch)
        v = self._glyph.get(k)
        if v is None:
            f = self._ft.get(path)
            if f is None:
                if not pygame.freetype.get_init():
                    pygame.freetype.init()
                try:
                    f = self._ft[path] = pygame.freetype.Font(path, 12)
                except (OSError, TypeError):
                    f = self._ft[path] = False
            try:
                v = bool(f) and f.get_metrics(ch)[0] is not None
            except Exception:
                v = False
            self._glyph[k] = v
        return v

    def _add_script_fonts(self, bold):
        if self._scripts_added[bold]:
            return
        self._scripts_added[bold] = True
        for lang in self._SCRIPT_LANGS:
            f = i18n.font_files(lang)[1 if bold else 0]
            if f and f not in self.chain[bold]:
                self.chain[bold].append(f)

    def font(self, size, bold=False, path=None):
        size = max(6, int(round(size)))
        path = path or self.chain[bold][0]
        k = (size, path)
        f = self._fonts.get(k)
        if f is None:
            try:
                f = pygame.font.Font(path, size)
            except (OSError, FileNotFoundError, TypeError):
                f = pygame.font.Font(None, size)
            self._fonts[k] = f
        return f

    def _pick(self, ch, bold):
        if not ch.strip():
            return self.chain[bold][0]
        for path in self.chain[bold]:
            if self._has(path, ch):
                return path
        self._add_script_fonts(bold)
        for path in self.chain[bold]:
            if self._has(path, ch):
                return path
        return self.chain[bold][0]

    def _runs(self, text, size, bold, mono):
        """Splits text into (font, chunk) runs by which font has the glyphs."""
        if mono and self.mono:
            return [(self.font(size, bold, self.mono), text)]
        runs, cur, cur_p = [], "", None
        for ch in text:
            p = self._pick(ch, bold)
            if p != cur_p and cur:
                runs.append((self.font(size, bold, cur_p), cur))
                cur = ""
            cur_p = p
            cur += ch
        if cur:
            runs.append((self.font(size, bold, cur_p), cur))
        return runs

    def render(self, text, size, color, bold=False, mono=False):
        k = (text, int(round(size)), color, bold, mono)
        s = self._cache.get(k)
        if s is None:
            runs = self._runs(text, size, bold, mono)
            parts = [f.render(chunk, True, color) for f, chunk in runs]
            asc = max((f.get_ascent() for f, _ in runs), default=0)
            desc = max((-f.get_descent() for f, _ in runs), default=0)
            w = sum(p.get_width() for p in parts)
            s = pygame.Surface((max(1, w), max(1, asc + desc)), pygame.SRCALPHA)
            x = 0
            for (f, _), p in zip(runs, parts):
                s.blit(p, (x, asc - f.get_ascent()))
                x += p.get_width()
            s = (s, asc)
            if len(self._cache) > 600:
                self._cache.clear()
            self._cache[k] = s
        return s

    def width(self, text, size, bold=False, mono=False):
        return self.render(text, size, (0, 0, 0), bold, mono)[0].get_width()

    def fit(self, text, max_w, max_size, bold=False, mono=False):
        """The largest size up to max_size at which text fits max_w."""
        w = self.width(text, max_size, bold, mono)
        if w <= max_w or w == 0:
            return max_size
        size = max_size * max_w / w
        while size > 6 and self.width(text, size, bold, mono) > max_w:
            size *= 0.95
        return size

    def ascent(self, size, bold=False):
        return self.font(size, bold).get_ascent()

    def draw(self, surf, text, x, baseline, size, color, bold=False, mono=False, anchor="left"):
        """Draws text with its baseline at `baseline`. Returns the width."""
        s, asc = self.render(text, size, color, bold, mono)
        if anchor == "center":
            x -= s.get_width() / 2
        elif anchor == "right":
            x -= s.get_width()
        surf.blit(s, (int(round(x)), int(round(baseline - asc))))
        return s.get_width()

    def wrap(self, text, max_w, size, bold=False):
        """Word-wraps text (breaking anywhere for scripts without spaces). Returns lines."""
        lines = []
        for para in text.split("\n"):
            words = para.split(" ") if " " in para else list(para)
            sep = " " if " " in para else ""
            line = ""
            for w in words:
                trial = (line + sep + w) if line else w
                if self.width(trial, size, bold) <= max_w or not line:
                    line = trial
                else:
                    lines.append(line)
                    line = w
            lines.append(line)
        return lines


def rrect(surf, rect, radius, color):
    """Filled rounded rectangle with anti-aliased corners."""
    x, y, w, h = [int(round(v)) for v in rect]
    r = int(max(0, min(radius, w / 2, h / 2)))
    if w <= 0 or h <= 0:
        return
    if r < 2:
        pygame.draw.rect(surf, color, (x, y, w, h))
        return
    pygame.draw.rect(surf, color, (x + r, y, w - 2 * r, h))
    pygame.draw.rect(surf, color, (x, y + r, w, h - 2 * r))
    for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r), (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
        pygame.gfxdraw.aacircle(surf, cx, cy, r, color)
        pygame.gfxdraw.filled_circle(surf, cx, cy, r, color)


def circle(surf, cx, cy, r, color):
    cx, cy, r = int(round(cx)), int(round(cy)), int(round(r))
    if r <= 0:
        return
    pygame.gfxdraw.aacircle(surf, cx, cy, r, color)
    pygame.gfxdraw.filled_circle(surf, cx, cy, r, color)


def cog(surf, cx, cy, r, color, hole):
    import math
    for i in range(8):
        a = i * math.pi / 4
        circle(surf, cx + math.cos(a) * r * 1.2, cy + math.sin(a) * r * 1.2, r * 0.29, color)
    circle(surf, cx, cy, r, color)
    circle(surf, cx, cy, r * 0.42, hole)


def upper(text, lang):
    """Upper case for section titles (Turkish dotted i handled)."""
    if lang.split("-")[0] == "tr":
        text = text.replace("i", "İ")
    return text.upper()


# ------------------------------------------------------------------ energy-flow drawing

def mix(a, b, t):
    """Colour a blended toward b by t (0 = a, 1 = b)."""
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def thick_line(surf, a, b, width, color):
    """Anti-aliased line with round ends."""
    import math
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1
    ox, oy = -dy / n * width / 2, dx / n * width / 2
    pts = [(x1 + ox, y1 + oy), (x2 + ox, y2 + oy), (x2 - ox, y2 - oy), (x1 - ox, y1 - oy)]
    pygame.gfxdraw.aapolygon(surf, pts, color)
    pygame.gfxdraw.filled_polygon(surf, pts, color)
    circle(surf, x1, y1, width / 2, color)
    circle(surf, x2, y2, width / 2, color)


def ring(surf, cx, cy, r, width, color):
    """A full ring."""
    c = (int(round(cx)), int(round(cy)))
    pygame.gfxdraw.aacircle(surf, c[0], c[1], int(round(r)), color)
    pygame.draw.circle(surf, color, c, int(round(r)), max(1, int(round(width))))
    pygame.gfxdraw.aacircle(surf, c[0], c[1], int(round(r - width)), color)


def polygon(surf, pts, color):
    pygame.gfxdraw.aapolygon(surf, pts, color)
    pygame.gfxdraw.filled_polygon(surf, pts, color)


def bolt(cx, cy, h):
    """A lightning bolt, h tall."""
    return [(cx + h * 0.1, cy - h * 0.5), (cx - h * 0.3, cy + h * 0.06), (cx - h * 0.02, cy + h * 0.06),
            (cx - h * 0.1, cy + h * 0.5), (cx + h * 0.3, cy - h * 0.06), (cx + h * 0.02, cy - h * 0.06)]


def icon(surf, kind, cx, cy, s, color, bg, level=None):
    """Line icons, `s` across: charger (a plug), solar (a sun), car (DC-DC or alternator), loads (a house), battery (with a charge `level`
    0-100), and the readings' icons: volt, amp, power, starter, midpoint, temp, signal."""
    import math
    w = max(2, s * 0.09)
    if kind == "charger":            # a mains plug
        for dx in (-0.15, 0.15):
            thick_line(surf, (cx + s * dx, cy - s * 0.46), (cx + s * dx, cy - s * 0.24), w, color)
        rrect(surf, (cx - s * 0.3, cy - s * 0.26, s * 0.6, s * 0.36), s * 0.1, color)
        polygon(surf, bolt(cx, cy - s * 0.08, s * 0.28), bg)
        rrect(surf, (cx - s * 0.08, cy + s * 0.08, s * 0.16, s * 0.16), s * 0.03, color)
        thick_line(surf, (cx, cy + s * 0.22), (cx, cy + s * 0.46), w, color)
    elif kind == "solar":            # a sun
        circle(surf, cx, cy, s * 0.2, color)
        for i in range(8):
            a = i * math.pi / 4
            thick_line(surf, (cx + math.cos(a) * s * 0.32, cy + math.sin(a) * s * 0.32),
                       (cx + math.cos(a) * s * 0.46, cy + math.sin(a) * s * 0.46), w, color)
    elif kind == "car":              # a car: DC-DC charger or alternator
        polygon(surf, [(cx - s * 0.3, cy - s * 0.04), (cx - s * 0.19, cy - s * 0.34), (cx + s * 0.19, cy - s * 0.34),
                       (cx + s * 0.32, cy - s * 0.04)], color)
        for sx in (-1, 1):            # side windows
            polygon(surf, [(cx + sx * s * 0.03, cy - s * 0.08), (cx + sx * s * 0.03, cy - s * 0.27),
                           (cx + sx * s * 0.14, cy - s * 0.27), (cx + sx * s * 0.22, cy - s * 0.08)], bg)
        rrect(surf, (cx - s * 0.47, cy - s * 0.08, s * 0.94, s * 0.3), s * 0.1, color)
        for sx in (-1, 1):
            circle(surf, cx + sx * s * 0.25, cy + s * 0.24, s * 0.16, bg)
            circle(surf, cx + sx * s * 0.25, cy + s * 0.24, s * 0.12, color)
            circle(surf, cx + sx * s * 0.25, cy + s * 0.24, s * 0.05, bg)
    elif kind == "caravan":          # a caravan: body, window, door, wheel and drawbar
        l, r, t, b = cx - s * 0.5, cx + s * 0.32, cy - s * 0.38, cy + s * 0.22
        rrect(surf, (l, t, r - l, b - t), s * 0.16, color)
        rrect(surf, (l + w, t + w, r - l - 2 * w, b - t - 2 * w), s * 0.11, bg)
        rrect(surf, (l + s * 0.11, t + s * 0.13, s * 0.32, s * 0.17), s * 0.03, color)      # window
        rrect(surf, (cx + s * 0.05, t + s * 0.13, s * 0.15, b - t - s * 0.13), s * 0.03, color)  # door
        thick_line(surf, (r, b - s * 0.07), (cx + s * 0.5, b - s * 0.07), w, color)       # drawbar
        circle(surf, cx - s * 0.15, b + s * 0.07, s * 0.17, bg)
        circle(surf, cx - s * 0.15, b + s * 0.07, s * 0.125, color)
        circle(surf, cx - s * 0.15, b + s * 0.07, s * 0.05, bg)
    elif kind == "boat":             # a sailing boat: hull and two sails
        polygon(surf, [(cx - s * 0.48, cy + s * 0.14), (cx + s * 0.48, cy + s * 0.14), (cx + s * 0.32, cy + s * 0.4),
                       (cx - s * 0.32, cy + s * 0.4)], color)
        thick_line(surf, (cx - s * 0.02, cy - s * 0.48), (cx - s * 0.02, cy + s * 0.14), w * 0.8, color)
        polygon(surf, [(cx - s * 0.08, cy - s * 0.42), (cx - s * 0.08, cy + s * 0.06), (cx - s * 0.4, cy + s * 0.06)], color)
        polygon(surf, [(cx + s * 0.04, cy - s * 0.34), (cx + s * 0.04, cy + s * 0.06), (cx + s * 0.34, cy + s * 0.06)], color)
    elif kind == "loads":            # a house
        l, r, t, b = cx - s * 0.36, cx + s * 0.36, cy - s * 0.44, cy + s * 0.4
        eave = cy - s * 0.08
        for p, q in (((cx - s * 0.48, eave + s * 0.06), (cx, t)), ((cx, t), (cx + s * 0.48, eave + s * 0.06)),
                     ((l, eave), (l, b)), ((r, eave), (r, b)), ((l, b), (r, b))):
            thick_line(surf, p, q, w, color)
        rrect(surf, (cx - s * 0.1, cy + s * 0.1, s * 0.2, s * 0.3), s * 0.03, color)
    elif kind in ("battery", "midpoint"):
        bw, bh = s * 0.5, s * 0.8
        x, y = cx - bw / 2, cy - bh / 2 + s * 0.05
        rrect(surf, (cx - s * 0.1, y - s * 0.1, s * 0.2, s * 0.12), s * 0.03, color)
        rrect(surf, (x, y, bw, bh), s * 0.08, color)
        rrect(surf, (x + w, y + w, bw - 2 * w, bh - 2 * w), s * 0.05, bg)
        if kind == "midpoint":       # a battery split in two
            thick_line(surf, (x + 2 * w, y + bh / 2), (x + bw - 2 * w, y + bh / 2), w, color)
        elif level is not None and level > 0:
            fh = (bh - 4 * w) * min(100, level) / 100
            rrect(surf, (x + 2 * w, y + bh - 2 * w - fh, bw - 4 * w, fh), s * 0.03, color)
    elif kind == "starter":          # a car battery: wide, two terminals
        bw, bh = s * 0.84, s * 0.54
        x, y = cx - bw / 2, cy - bh / 2 + s * 0.08
        for tx in (x + bw * 0.22, x + bw * 0.78):
            rrect(surf, (tx - s * 0.08, y - s * 0.12, s * 0.16, s * 0.14), s * 0.03, color)
        rrect(surf, (x, y, bw, bh), s * 0.08, color)
        rrect(surf, (x + w, y + w, bw - 2 * w, bh - 2 * w), s * 0.05, bg)
        thick_line(surf, (x + bw * 0.14, y + bh * 0.45), (x + bw * 0.3, y + bh * 0.45), w * 0.8, color)
        thick_line(surf, (x + bw * 0.62, y + bh * 0.45), (x + bw * 0.86, y + bh * 0.45), w * 0.8, color)
        thick_line(surf, (x + bw * 0.74, y + bh * 0.3), (x + bw * 0.74, y + bh * 0.6), w * 0.8, color)
    elif kind == "volt":             # a lightning bolt
        polygon(surf, bolt(cx, cy, s * 0.95), color)
    elif kind == "amp":              # current: arrows both ways
        for yy, d in ((cy - s * 0.17, 1), (cy + s * 0.17, -1)):
            thick_line(surf, (cx - s * 0.4, yy), (cx + s * 0.4, yy), w, color)
            tip = cx + s * 0.44 * d
            polygon(surf, [(tip, yy), (tip - s * 0.2 * d, yy - s * 0.14), (tip - s * 0.2 * d, yy + s * 0.14)], color)
    elif kind == "power":            # a bolt in a ring
        ring(surf, cx, cy, s * 0.46, w, color)
        polygon(surf, bolt(cx, cy, s * 0.56), color)
    elif kind == "temp":             # a thermometer
        circle(surf, cx, cy + s * 0.28, s * 0.17, color)
        rrect(surf, (cx - s * 0.1, cy - s * 0.46, s * 0.2, s * 0.7), s * 0.1, color)
        rrect(surf, (cx - s * 0.1 + w, cy - s * 0.46 + w, s * 0.2 - 2 * w, s * 0.5), s * 0.06, bg)
    elif kind == "signal":           # four bars
        bw = s * 0.16
        for i in range(4):
            h = s * (0.25 + 0.2 * i)
            rrect(surf, (cx - s * 0.44 + i * s * 0.24, cy + s * 0.4 - h, bw, h), bw * 0.3, color)


def badge(surf, cx, cy, r, color, bg, plus):
    """A small round - or + badge."""
    circle(surf, cx, cy, r + max(1.5, r * 0.3), bg)
    circle(surf, cx, cy, r, color)
    w = max(1.5, r * 0.32)
    pygame.draw.rect(surf, bg, (int(round(cx - r * 0.55)), int(round(cy - w / 2)), int(round(r * 1.1)), max(1, int(round(w)))))
    if plus:
        pygame.draw.rect(surf, bg, (int(round(cx - w / 2)), int(round(cy - r * 0.55)), max(1, int(round(w))), int(round(r * 1.1))))
