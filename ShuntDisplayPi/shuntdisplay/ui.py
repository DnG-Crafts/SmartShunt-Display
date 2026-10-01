"""Touch screens: settings, hex keypad, choice lists, steppers, "Find nearby" and a confirm box.

Everything is sized in units of `u` (about 1/400 of the screen's shorter side), so the same
layouts work from a 3.5" 480x320 screen up to a 1080p monitor, in either orientation.
"""
import time

import pygame

from . import gfx
from .victron import normalise_mac


class Ctx:
    """What every page needs: strings, text renderer, colours, unit size and the app."""
    def __init__(self, app):
        self.app = app

    @property
    def t(self): return self.app.strings
    @property
    def txt(self): return self.app.text
    @property
    def c(self): return self.app.theme
    @property
    def u(self): return self.app.u


def _inside(rect, x, y):
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


class Button:
    def __init__(self, label, on_tap, style="text", enabled=True):
        self.label, self.on_tap, self.style, self.enabled = label, on_tap, style, enabled
        self.rect = (0, 0, 0, 0)
        self.pressed = False
        self.repeat = False          # keeps firing while held (stepper +/-)

    def draw(self, surf, ctx, size=None):
        c, u = ctx.c, ctx.u
        x, y, w, h = self.rect
        size = size or 16 * u
        if self.style == "key":
            gfx.rrect(surf, self.rect, 10 * u, c["press"] if self.pressed else c["key"])
            col = c["text"] if self.enabled else c["muted"]
        else:
            if self.pressed:
                gfx.rrect(surf, self.rect, 10 * u, c["press"])
            col = (c["muted"] if not self.enabled else c["good"] if self.style == "primary"
                   else c["bad"] if self.style == "danger" else c["text"])
        bold = self.style in ("primary", "key")
        s = ctx.txt.fit(self.label, w - 16 * u, size, bold=bold)
        base = y + h / 2 + ctx.txt.ascent(s, bold) * 0.36
        ctx.txt.draw(surf, self.label, x + w / 2, base, s, col, bold=bold, anchor="center")


class Page:
    """Base page: a header (left button, title, right button) and buttons that react to taps."""
    title = ""

    def __init__(self, ctx):
        self.ctx = ctx
        self.buttons = []
        self.left = self.right = None
        self._pressed = None
        self._down_at = 0
        self._last_repeat = 0

    @property
    def t(self): return self.ctx.t

    def header(self, surf, title):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        W = surf.get_width()
        hh = 56 * u
        bw = min(W * 0.3, 130 * u)
        if self.left:
            self.left.rect = (4 * u, 4 * u, bw, hh - 8 * u)
            self.left.draw(surf, self.ctx)
        if self.right:
            self.right.rect = (W - bw - 4 * u, 4 * u, bw, hh - 8 * u)
            self.right.draw(surf, self.ctx)
        tw = W - 2 * (bw + 8 * u) if (self.left or self.right) else W - 32 * u
        s = txt.fit(title, tw, 20 * u, bold=True)
        txt.draw(surf, title, W / 2, hh / 2 + txt.ascent(s, True) * 0.36, s, c["text"], bold=True, anchor="center")
        return hh

    def all_buttons(self):
        return [b for b in [self.left, self.right] + self.buttons if b]

    def down(self, x, y):
        for b in self.all_buttons():
            if b.enabled and _inside(b.rect, x, y):
                b.pressed = True
                self._pressed = b
                self._down_at = self._last_repeat = time.monotonic()
                if b.repeat:
                    b.on_tap()
                return True
        return False

    def move(self, x, y):
        b = self._pressed
        if b and not _inside(b.rect, x, y):
            b.pressed = False
            self._pressed = None

    def up(self, x, y):
        b = self._pressed
        self._pressed = None
        if b:
            b.pressed = False
            if not b.repeat and _inside(b.rect, x, y):
                b.on_tap()
            return True
        return False

    def tick(self, now):
        b = self._pressed
        if b and b.repeat and now - self._down_at > 0.45 and now - self._last_repeat > 0.08:
            self._last_repeat = now
            b.on_tap()
            return True
        return False

    def wheel(self, d):
        pass


class Row:
    """One row in a scrolling settings list."""
    def __init__(self, kind, label="", value="", on_tap=None, on=False, key=None):
        self.kind, self.label, self.value, self.on_tap, self.on = kind, label, value, on_tap, on
        # identifies the row across redraws (pages rebuild their rows every frame)
        self.key = key if key is not None else (kind, label)
        self.rect = (0, 0, 0, 0)
        self.height = 0


class ScrollList:
    """Rows grouped into cards under section titles, scrolled by dragging (or the mouse wheel)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.offset = 0
        self.rows = []
        self.area = (0, 0, 0, 0)
        self._down = None
        self._dragging = False
        self._pressed = None         # key of the row under the finger
        self._content_h = 0

    def _measure(self, row, w):
        u, txt = self.ctx.u, self.ctx.txt
        if row.kind == "section":
            return 44 * u
        if row.kind == "text":
            lines = txt.wrap(row.label, w - 32 * u, 13 * u)
            return (len(lines) * 19 + 16) * u
        if row.kind == "space":
            return 12 * u
        if row.kind == "device":
            return 72 * u
        return 56 * u

    def layout(self, rows, area):
        self.rows = rows
        self.area = area
        ax, ay, aw, ah = area
        y = 0
        for r in rows:
            r.height = self._measure(r, aw)
            r.rect = (ax, y, aw, r.height)
            y += r.height
        self._content_h = y + 16 * self.ctx.u
        self.clamp()

    def clamp(self):
        self.offset = max(0, min(self.offset, max(0, self._content_h - self.area[3])))

    def draw(self, surf):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        ax, ay, aw, ah = self.area
        clip = surf.get_clip()
        surf.set_clip((int(ax), int(ay), int(aw), int(ah)))
        base = ay - self.offset
        # cards: consecutive non-section rows
        i = 0
        while i < len(self.rows):
            if self.rows[i].kind in ("section", "space"):
                i += 1
                continue
            j = i
            while j < len(self.rows) and self.rows[j].kind not in ("section", "space"):
                j += 1
            top = self.rows[i].rect[1] + base
            bottom = self.rows[j - 1].rect[1] + self.rows[j - 1].height + base
            if bottom > ay and top < ay + ah:
                gfx.rrect(surf, (ax + 12 * u, top, aw - 24 * u, bottom - top), 14 * u, c["panel"])
            i = j
        for k, r in enumerate(self.rows):
            x, y, w, h = r.rect
            y += base
            if y > ay + ah or y + h < ay:
                continue
            self._draw_row(surf, r, x + 12 * u, y, w - 24 * u, h,
                           k + 1 < len(self.rows) and self.rows[k + 1].kind not in ("section", "space", "text"))
        surf.set_clip(clip)
        # scroll hint
        if self._content_h > ah:
            frac = ah / self._content_h
            bh = max(24 * u, ah * frac)
            by = ay + (ah - bh) * (self.offset / max(1, self._content_h - ah))
            gfx.rrect(surf, (ax + aw - 5 * u, by, 3 * u, bh), 1.5 * u, c["line"])

    def _draw_row(self, surf, r, x, y, w, h, divider):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        pad = 16 * u
        if r.kind == "section":
            t = gfx.upper(r.label, self.ctx.t.tag)
            txt.draw(surf, t, x + 8 * u, y + h - 12 * u, txt.fit(t, w, 13 * u, True), c["muted"], bold=True)
            return
        if r.kind == "text":
            yy = y + 8 * u + txt.ascent(13 * u)
            for line in txt.wrap(r.label, w - 2 * pad, 13 * u):
                txt.draw(surf, line, x + pad if not r.on else x + w / 2, yy, 13 * u, c["muted"],
                         anchor="center" if r.on else "left")
                yy += 19 * u
            return
        if r.kind == "space":
            return
        if self._pressed is not None and r.key == self._pressed:
            gfx.rrect(surf, (x, y, w, h), 14 * u, c["press"])
        if r.kind == "device":
            s1 = txt.fit(r.label, w - 2 * pad, 17 * u, True)
            txt.draw(surf, r.label, x + pad, y + h * 0.45, s1, c["text"], bold=True)
            s2 = txt.fit(r.value, w - 2 * pad, 13 * u, mono=True)
            txt.draw(surf, r.value, x + pad, y + h * 0.45 + 22 * u, s2, c["muted"], mono=True)
            return
        mid = y + h / 2 + txt.ascent(16 * u) * 0.36
        if r.kind == "choice":
            rr = 11 * u
            cx = x + w - pad - rr
            ls = txt.fit(r.label, w - 3 * pad - 2 * rr, 16 * u)
            txt.draw(surf, r.label, x + pad, mid, ls, c["text"])
            gfx.circle(surf, cx, y + h / 2, rr, c["good"] if r.on else c["muted"])
            gfx.circle(surf, cx, y + h / 2, rr - 2.5 * u, c["press"] if r.key == self._pressed else c["panel"])
            if r.on:
                gfx.circle(surf, cx, y + h / 2, rr * 0.5, c["good"])
        elif r.kind == "button":
            col = c["bad"] if r.on else c["good"]
            s = txt.fit(r.label, w - 2 * pad, 16 * u, True)
            txt.draw(surf, r.label, x + w / 2, mid, s, col, bold=True, anchor="center")
        elif r.kind == "toggle":
            sw, sh = 40 * u, 22 * u
            sx, sy = x + w - pad - sw, y + (h - sh) / 2
            ls = txt.fit(r.label, sx - x - pad - 8 * u, 16 * u)
            txt.draw(surf, r.label, x + pad, mid, ls, c["text"])
            gfx.rrect(surf, (sx, sy + 3 * u, sw, sh - 6 * u), (sh - 6 * u) / 2,
                      c["good"] if r.on else c["line"])
            tx = sx + sw - sh / 2 if r.on else sx + sh / 2
            gfx.circle(surf, tx, sy + sh / 2, sh / 2, c["good"] if r.on else c["muted"])
        else:  # value row: label, value and a chevron
            chev = 10 * u
            vw = txt.width(r.value, 15 * u) if r.value else 0
            lw_max = w - 2 * pad - chev - 12 * u
            label_w = min(txt.width(r.label, 16 * u), lw_max * (0.6 if r.value else 1))
            ls = txt.fit(r.label, label_w, 16 * u)
            txt.draw(surf, r.label, x + pad, mid, ls, c["text"])
            if r.value:
                avail = lw_max - txt.width(r.label, ls) - 12 * u
                vs = txt.fit(r.value, max(20 * u, avail), 15 * u)
                txt.draw(surf, r.value, x + w - pad - chev - 8 * u, mid, vs, c["muted"], anchor="right")
            cx, cy = x + w - pad - chev / 2, y + h / 2
            pygame.draw.lines(surf, c["muted"], False, [(cx - chev * 0.25, cy - chev * 0.45), (cx + chev * 0.25, cy),
                                                        (cx - chev * 0.25, cy + chev * 0.45)], max(2, int(2 * u)))
        if divider:
            pygame.draw.line(surf, c["line"], (x + pad, y + h - 1), (x + w - pad, y + h - 1), 1)

    def _row_at(self, x, y):
        ax, ay, aw, ah = self.area
        if not _inside(self.area, x, y):
            return None
        yy = y - ay + self.offset
        for r in self.rows:
            if r.rect[1] <= yy < r.rect[1] + r.height:
                return r if r.kind in ("value", "toggle", "button", "device", "choice") and r.on_tap else None
        return None

    def down(self, x, y):
        if not _inside(self.area, x, y):
            return False
        self._down = (x, y, self.offset)
        self._dragging = False
        r = self._row_at(x, y)
        self._pressed = r.key if r else None
        return True

    def move(self, x, y):
        if not self._down:
            return
        dx, dy = x - self._down[0], y - self._down[1]
        if not self._dragging and abs(dy) > 10 * self.ctx.u:
            self._dragging = True
            self._pressed = None
        if self._dragging:
            self.offset = self._down[2] - dy
            self.clamp()

    def up(self, x, y):
        was = self._down
        self._down = None
        key = self._pressed
        self._pressed = None
        r = self._row_at(x, y)
        if was and not self._dragging and key is not None and r and r.key == key:
            r.on_tap()
        return bool(was)

    def wheel(self, d):
        self.offset += d * 60 * self.ctx.u
        self.clamp()


# ------------------------------------------------------------------ settings

class SettingsPage(Page):
    def __init__(self, ctx, settings):
        super().__init__(ctx)
        self.original = settings.copy()
        self.s = settings.copy()
        self.list = ScrollList(ctx)
        self.left = Button(self.t("cancel"), self.cancel)
        self.right = Button(self.t("save"), self.save, "primary")

    def _key_text(self):
        k = self.s.key
        return k[:4] + "…" + k[-4:] if k else self.t("pi_not_set")

    def _rows(self):
        t, s, app = self.t, self.s, self.ctx.app
        tags, names = app.languages
        lang_name = names[tags.index(s.language)] if s.language in tags else t("language_system")
        off = s.screen_off
        rows = [
            Row("section", t("section_shunt")),
            Row("value", t("mac_label"), s.mac or t("pi_not_set"), self.edit_mac),
            Row("value", t("find_nearby"), "", self.find_nearby),
            Row("value", t("key_label"), self._key_text(), self.edit_key),
            Row("toggle", t("demo_label"), on_tap=self.toggle_demo, on=s.demo),
            Row("text", t("mac_key_help")),
            Row("section", t("section_chargers")),
        ]
        for i in range(len(s.charger_mac)):
            rows.append(Row("value", t("charger_n", i + 1), s.charger_mac[i] or t("charger_not_used"),
                            (lambda i=i: self.edit_charger(i)), key=("charger", i)))
        rows += [
            Row("value", t("other_source_label"),
                t("source_auto") if s.other_source == "auto" else source_name(t, s.other_source, True),
                self.pick_other_source),
            Row("text", t("chargers_help")),
            Row("section", t("section_display")),
            Row("value", t("language_label"), lang_name, self.pick_language),
            Row("value", t("theme_label"), t("theme_light") if s.theme == 1 else t("theme_dark"), self.pick_theme),
            Row("value", t("pi_rotation_label"), "%d°" % s.screen_rotation, self.pick_rotation),
            Row("value", t("loads_icon_label"), t("icon_" + s.loads_icon), self.pick_loads_icon),
        ]
        if app.backlight.available:
            rows.append(Row("value", t("pi_brightness_label"), t("percent_value", s.brightness), self.edit_brightness))
        rows += [
            Row("value", t("pi_screen_off_label"), app.duration_label(off), self.pick_screen_off),
            Row("section", t("section_alerts")),
            Row("value", t("stale_label"), t("seconds_value", s.stale_after), self.edit_stale),
            Row("value", t("amber_label"), t("percent_value", s.soc_amber), self.edit_amber),
            Row("value", t("red_label"), t("percent_value", s.soc_red), self.edit_red),
            Row("space"),
        ]
        if app.can_exit:
            rows += [Row("button", t("pi_exit"), on_tap=app.quit, on=True), Row("space")]
        about = Row("text", t("pi_about", app.VERSION) + "\n" + t("pi_settings_file", app.config_path))
        about.on = True   # centred
        rows.append(about)
        return rows

    def draw(self, surf):
        surf.fill(self.ctx.c["bg"])
        hh = self.header(surf, self.t("settings"))
        W, H = surf.get_size()
        self.list.layout(self._rows(), (0, hh, W, H - hh))
        self.list.draw(surf)

    def down(self, x, y):
        return super().down(x, y) or self.list.down(x, y)

    def move(self, x, y):
        super().move(x, y)
        self.list.move(x, y)

    def up(self, x, y):
        return super().up(x, y) or self.list.up(x, y)

    def wheel(self, d):
        self.list.wheel(d)

    # -------------------------------------------------------------- actions

    def changed(self):
        return self.s != self.original

    def cancel(self):
        if self.changed():
            self.ctx.app.push(ConfirmPage(self.ctx, self.t("discard_changes"), self.t("discard"),
                                          self.t("keep_editing"), lambda: self.ctx.app.pop(2)))
        else:
            self.ctx.app.pop()

    def save(self):
        if self.s.soc_red > self.s.soc_amber:
            self.s.soc_red = self.s.soc_amber
        self.ctx.app.apply_settings(self.s)

    def edit_mac(self):
        def done(v): self.s.mac = normalise_mac(v) if v else ""
        self.ctx.app.push(KeypadPage(self.ctx, self.t("mac_label"), 12, self.s.mac.replace(":", ""), done))

    def edit_key(self):
        def done(v): self.s.key = v
        self.ctx.app.push(KeypadPage(self.ctx, self.t("key_label"), 32, self.s.key, done))

    def find_nearby(self):
        def done(mac): self.s.mac = mac
        self.ctx.app.push(NearbyPage(self.ctx, done))

    def edit_charger(self, i):
        self.ctx.app.push(ChargerPage(self.ctx, self.s, i))

    def pick_other_source(self):
        from .config import OTHER_SOURCES
        opts = [(v, source_name(self.t, v, v != "auto" or bool(self.s.chargers()))) for v in OTHER_SOURCES]
        opts[0] = ("auto", self.t("source_auto") + " (" + source_name(self.t, "auto", bool(self.s.chargers())) + ")")
        def done(v): self.s.other_source = v
        self.ctx.app.push(ChoicePage(self.ctx, self.t("other_source_label"), opts, self.s.other_source, done))

    def toggle_demo(self):
        self.s.demo = not self.s.demo

    def pick_language(self):
        tags, names = self.ctx.app.languages
        opts = [("", self.t("language_system"))] + list(zip(tags, names))
        def done(v): self.s.language = v
        self.ctx.app.push(ChoicePage(self.ctx, self.t("language_label"), opts, self.s.language, done))

    def pick_theme(self):
        opts = [(2, self.t("theme_dark")), (1, self.t("theme_light"))]
        def done(v): self.s.theme = v
        self.ctx.app.push(ChoicePage(self.ctx, self.t("theme_label"), opts, self.s.theme, done))

    def pick_loads_icon(self):
        from .config import LOADS_ICONS
        opts = [(v, self.t("icon_" + v)) for v in LOADS_ICONS]
        def done(v): self.s.loads_icon = v
        self.ctx.app.push(ChoicePage(self.ctx, self.t("loads_icon_label"), opts, self.s.loads_icon, done))

    def pick_rotation(self):
        opts = [(d, "%d°" % d) for d in (0, 90, 180, 270)]
        def done(v): self.s.screen_rotation = v
        self.ctx.app.push(ChoicePage(self.ctx, self.t("pi_rotation_label"), opts, self.s.screen_rotation, done))

    def pick_screen_off(self):
        from .config import SCREEN_OFF_CHOICES
        choices = list(SCREEN_OFF_CHOICES)
        if self.s.screen_off not in choices:
            choices = sorted(choices + [self.s.screen_off])
        opts = [(v, self.ctx.app.duration_label(v)) for v in choices]
        def done(v): self.s.screen_off = v
        self.ctx.app.push(ChoicePage(self.ctx, self.t("pi_screen_off_label"), opts, self.s.screen_off, done))

    def _stepper(self, title, attr, lo, hi, step, label, live=None):
        def done(v): setattr(self.s, attr, v)
        self.ctx.app.push(StepperPage(self.ctx, title, getattr(self.s, attr), lo, hi, step, label, done, live))

    def edit_brightness(self):
        app = self.ctx.app
        self._stepper(self.t("pi_brightness_label"), "brightness", 10, 100, 10,
                      lambda v: self.t("percent_value", v), live=app.backlight.set_brightness)

    def edit_stale(self):
        self._stepper(self.t("stale_label"), "stale_after", min(5, self.s.stale_after), max(600, self.s.stale_after), 5,
                      lambda v: self.t("seconds_value", v))

    def edit_amber(self):
        self._stepper(self.t("amber_label"), "soc_amber", 0, 100, 5, lambda v: self.t("percent_value", v))

    def edit_red(self):
        self._stepper(self.t("red_label"), "soc_red", 0, 100, 5, lambda v: self.t("percent_value", v))


def source_name(t, source, have_chargers):
    """The label for charging the extra chargers don't account for."""
    if source == "auto":
        return t("dash_other") if have_chargers else t("dash_charger")
    return t(dict(dcdc="dash_dcdc", solar="dash_solar", mains="dash_mains", alternator="dash_alternator")[source])


class ChargerPage(Page):
    """One extra charger: MAC address (typed or found nearby), key, and Remove. Edits the
    settings page's copy; Save on that page keeps them."""

    def __init__(self, ctx, settings, slot):
        super().__init__(ctx)
        self.s, self.slot = settings, slot
        self.right = Button(self.t("pi_done"), ctx.app.pop, "primary")
        self.list = ScrollList(ctx)

    def _key_text(self):
        k = self.s.charger_key[self.slot]
        return k[:4] + "…" + k[-4:] if k else self.t("pi_not_set")

    def _rows(self):
        t, i = self.t, self.slot
        rows = [
            Row("space"),
            Row("value", t("mac_label"), self.s.charger_mac[i] or t("pi_not_set"), self.edit_mac),
            Row("value", t("find_nearby"), "", self.find_nearby),
            Row("value", t("key_label"), self._key_text(), self.edit_key),
            Row("text", t("charger_key_help")),
        ]
        if self.s.charger_mac[i] or self.s.charger_key[i]:
            rows += [Row("space"), Row("button", t("remove_charger"), on_tap=self.remove, on=True)]
        return rows

    def edit_mac(self):
        i = self.slot
        def done(v): self.s.charger_mac[i] = normalise_mac(v) if v else ""
        self.ctx.app.push(KeypadPage(self.ctx, self.t("mac_label"), 12, self.s.charger_mac[i].replace(":", ""), done))

    def edit_key(self):
        i = self.slot
        def done(v): self.s.charger_key[i] = v
        self.ctx.app.push(KeypadPage(self.ctx, self.t("key_label"), 32, self.s.charger_key[i], done))

    def find_nearby(self):
        i = self.slot
        def done(mac): self.s.charger_mac[i] = mac
        self.ctx.app.push(NearbyPage(self.ctx, done, chargers=True))

    def remove(self):
        self.s.charger_mac[self.slot] = self.s.charger_key[self.slot] = ""
        self.ctx.app.pop()

    def draw(self, surf):
        surf.fill(self.ctx.c["bg"])
        hh = self.header(surf, self.t("charger_n", self.slot + 1))
        W, H = surf.get_size()
        self.list.layout(self._rows(), (0, hh, W, H - hh))
        self.list.draw(surf)

    def down(self, x, y):
        return super().down(x, y) or self.list.down(x, y)

    def move(self, x, y):
        super().move(x, y)
        self.list.move(x, y)

    def up(self, x, y):
        return super().up(x, y) or self.list.up(x, y)

    def wheel(self, d):
        self.list.wheel(d)


# ------------------------------------------------------------------ hex keypad

class KeypadPage(Page):
    """Hex keypad for the MAC address (12 digits) or the key (32 digits)."""

    def __init__(self, ctx, title, want, value, on_done):
        super().__init__(ctx)
        self.title, self.want, self.value, self.on_done = title, want, value or "", on_done
        self.left = Button(self.t("cancel"), ctx.app.pop)
        self.right = Button(self.t("pi_done"), self.done, "primary")
        self.keys = [Button(ch.upper(), (lambda ch=ch: self.type(ch)), "key") for ch in "0123456789abcdef"]
        self.back = Button("⌫", self.backspace, "key")
        self.back.repeat = True
        self.clear = Button(self.t("pi_clear"), self.clear_all, "key")
        self.buttons = self.keys + [self.back, self.clear]
        self._update()

    def _update(self):
        self.right.enabled = len(self.value) in (0, self.want)   # Done: complete, or empty to clear it

    def type(self, ch):
        if len(self.value) < self.want:
            self.value += ch
        self._update()

    def backspace(self):
        self.value = self.value[:-1]
        self._update()

    def clear_all(self):
        self.value = ""
        self._update()

    def done(self):
        if len(self.value) in (0, self.want):
            self.on_done(self.value)
            self.ctx.app.pop()

    def draw(self, surf):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        surf.fill(c["bg"])
        hh = self.header(surf, self.title)
        W, H = surf.get_size()
        landscape = W > H
        cols = 9 if landscape else 6
        rows = 2 if landscape else 3
        gap = 8 * u
        key_h = min(72 * u, (H - hh) * (0.45 if landscape else 0.42) / rows)
        grid_h = rows * key_h + (rows - 1) * gap
        key_w = (W - 2 * 12 * u - (cols - 1) * gap) / cols
        top = H - 12 * u - grid_h
        order = self.keys + [self.back, self.clear]
        for i, b in enumerate(order):
            r, col = divmod(i, cols)
            b.rect = (12 * u + col * (key_w + gap), top + r * (key_h + gap), key_w, key_h)
            b.draw(surf, self.ctx, size=min(26 * u, key_h * 0.42))

        # the value, typed digits bright and the rest as placeholders
        area_top, area_bottom = hh + 8 * u, top - 12 * u
        full_chars = self.value + "_" * (self.want - len(self.value))
        if self.want == 12:
            lines = [":".join(full_chars[i:i + 2] for i in range(0, 12, 2))]
            typed_len = [len(self.value) + max(0, (len(self.value) - 1) // 2) if self.value else 0]
        else:
            lines = [" ".join(full_chars[j:j + 4] for j in range(i, i + 16, 4)) for i in (0, 16)]
            typed_len = []
            for i in (0, 16):
                n = max(0, min(16, len(self.value) - i))
                typed_len.append(n + max(0, (n - 1) // 4) if n else 0)
        count = self.t("pi_chars_count", len(self.value), self.want)
        line_size = txt.fit(max(lines, key=len), W - 48 * u, 40 * u, mono=True)
        line_size = min(line_size, (area_bottom - area_top - 30 * u) / (len(lines) * 1.3))
        block = len(lines) * line_size * 1.3
        y = area_top + (area_bottom - area_top - block - 24 * u) / 2 + line_size
        for line, n in zip(lines, typed_len):
            x = W / 2 - txt.width(line, line_size, mono=True) / 2
            txt.draw(surf, line, x, y, line_size, c["muted"], mono=True)
            if n:
                txt.draw(surf, line[:n], x, y, line_size, c["text"], mono=True)
            y += line_size * 1.3
        txt.draw(surf, count, W / 2, y + 4 * u, 14 * u, c["muted"], anchor="center")


# ------------------------------------------------------------------ choice list

class ChoicePage(Page):
    def __init__(self, ctx, title, options, current, on_done):
        super().__init__(ctx)
        self.title, self.options, self.current, self.on_done = title, options, current, on_done
        self.left = Button(self.t("cancel"), ctx.app.pop)
        self.list = ScrollList(ctx)
        self._scrolled = False

    def _pick(self, v):
        self.on_done(v)
        self.ctx.app.pop()

    def draw(self, surf):
        c, u = self.ctx.c, self.ctx.u
        surf.fill(c["bg"])
        hh = self.header(surf, self.title)
        W, H = surf.get_size()
        rows = [Row("space")]
        for v, label in self.options:
            rows.append(Row("choice", label, on_tap=lambda v=v: self._pick(v), on=(v == self.current), key=("choice", v)))
        self.list.layout(rows, (0, hh, W, H - hh))
        if not self._scrolled:   # start with the current choice in view
            self._scrolled = True
            for r in rows:
                if r.on:
                    self.list.offset = r.rect[1] - (H - hh) / 2 + r.height / 2
                    self.list.clamp()
        self.list.draw(surf)

    def down(self, x, y):
        return super().down(x, y) or self.list.down(x, y)

    def move(self, x, y):
        super().move(x, y)
        self.list.move(x, y)

    def up(self, x, y):
        return super().up(x, y) or self.list.up(x, y)

    def wheel(self, d):
        self.list.wheel(d)


# ------------------------------------------------------------------ stepper

class StepperPage(Page):
    def __init__(self, ctx, title, value, lo, hi, step, label, on_done, live=None):
        super().__init__(ctx)
        self.title, self.value, self.lo, self.hi, self.step = title, value, lo, hi, step
        self.label, self.on_done, self.live, self.start = label, on_done, live, value
        self.left = Button(self.t("cancel"), self.cancel)
        self.right = Button(self.t("pi_done"), self.done, "primary")
        self.minus = Button("−", lambda: self.change(-1), "key")
        self.plus = Button("+", lambda: self.change(1), "key")
        self.minus.repeat = self.plus.repeat = True
        self.buttons = [self.minus, self.plus]

    def change(self, d):
        v = (self.value // self.step) * self.step if d < 0 and self.value % self.step else self.value + d * self.step
        self.value = max(self.lo, min(self.hi, v))
        if self.live:
            self.live(self.value)

    def cancel(self):
        if self.live:
            self.live(self.start)
        self.ctx.app.pop()

    def done(self):
        self.on_done(self.value)
        self.ctx.app.pop()

    def draw(self, surf):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        surf.fill(c["bg"])
        hh = self.header(surf, self.title)
        W, H = surf.get_size()
        mid = hh + (H - hh) / 2
        bs = min(110 * u, (H - hh) * 0.5, W * 0.25)
        self.minus.rect = (W * 0.08, mid - bs / 2, bs, bs)
        self.plus.rect = (W * 0.92 - bs, mid - bs / 2, bs, bs)
        self.minus.enabled = self.value > self.lo
        self.plus.enabled = self.value < self.hi
        self.minus.draw(surf, self.ctx, size=bs * 0.5)
        self.plus.draw(surf, self.ctx, size=bs * 0.5)
        text = self.label(self.value)
        s = txt.fit(text, W * 0.84 - 2 * bs - 16 * u, 64 * u, bold=True)
        txt.draw(surf, text, W / 2, mid + txt.ascent(s, True) * 0.36, s, c["text"], bold=True, anchor="center")


# ------------------------------------------------------------------ find nearby

class NearbyPage(Page):
    def __init__(self, ctx, on_done, chargers=False):
        super().__init__(ctx)
        self.on_done = on_done
        self.chargers = chargers
        self.left = None
        self.right = Button(self.t("cancel"), ctx.app.pop)
        self.list = ScrollList(ctx)

    def _pick(self, mac):
        self.on_done(mac)
        self.ctx.app.pop()

    def draw(self, surf):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        app = self.ctx.app
        surf.fill(c["bg"])
        hh = self.header(surf, self.t("nearby_chargers_title" if self.chargers else "nearby_title"))
        W, H = surf.get_size()
        found, others = app.nearby_list(self.chargers)
        status = app.nearby_status(others, self.chargers)
        y = hh
        for line in txt.wrap(status, W - 32 * u, 13 * u):
            txt.draw(surf, line, 16 * u, y + txt.ascent(13 * u), 13 * u, c["muted"])
            y += 19 * u
        y += 6 * u
        if not found:
            yy = y + (H - y) / 3
            empty = self.t("nearby_chargers_empty" if self.chargers else "nearby_empty")
            for line in txt.wrap(empty, W - 64 * u, 15 * u):
                txt.draw(surf, line, W / 2, yy, 15 * u, c["muted"], anchor="center")
                yy += 22 * u
            self.list.layout([], (0, y, W, H - y))
            return
        rows = []
        for f in found:
            r = Row("device", f["title"], f["subtitle"], (lambda m=f["mac"]: self._pick(m)), key=("device", f["mac"]))
            rows.append(r)
            rows.append(Row("space"))
        self.list.layout(rows, (0, y, W, H - y))
        self.list.draw(surf)

    def down(self, x, y):
        return super().down(x, y) or self.list.down(x, y)

    def move(self, x, y):
        super().move(x, y)
        self.list.move(x, y)

    def up(self, x, y):
        return super().up(x, y) or self.list.up(x, y)

    def wheel(self, d):
        self.list.wheel(d)


# ------------------------------------------------------------------ confirm box

class ConfirmPage(Page):
    """A question over the page below it: [no] [yes]."""
    overlay = True

    def __init__(self, ctx, question, yes, no, on_yes):
        super().__init__(ctx)
        self.question = question
        self.yes = Button(yes, on_yes, "danger")
        self.no = Button(no, ctx.app.pop, "primary")
        self.buttons = [self.no, self.yes]

    def draw(self, surf):
        c, u, txt = self.ctx.c, self.ctx.u, self.ctx.txt
        W, H = surf.get_size()
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        surf.blit(veil, (0, 0))
        bw = min(W - 48 * u, 420 * u)
        lines = txt.wrap(self.question, bw - 48 * u, 17 * u)
        bh = 24 * u + len(lines) * 26 * u + 16 * u + 52 * u + 16 * u
        bx, by = (W - bw) / 2, (H - bh) / 2
        gfx.rrect(surf, (bx, by, bw, bh), 16 * u, c["panel"])
        y = by + 24 * u + txt.ascent(17 * u)
        for line in lines:
            txt.draw(surf, line, W / 2, y, 17 * u, c["text"], anchor="center")
            y += 26 * u
        half = (bw - 48 * u) / 2
        self.no.rect = (bx + 16 * u, by + bh - 68 * u, half, 52 * u)
        self.yes.rect = (bx + 32 * u + half, by + bh - 68 * u, half, 52 * u)
        self.no.draw(surf, self.ctx)
        self.yes.draw(surf, self.ctx)
