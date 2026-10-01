"""The dashboard, in the same design as the AlphaESS display: a live energy-flow picture (the
charge sources, the battery and the loads around a hub, with dots running along the lines the way the
energy flows), a state-of-charge card and a card of the shunt's readings.
Landscape puts the flow picture on the left and the cards on the right; portrait stacks them.

The shunt measures only the battery, so on its own the picture shows the battery's net flow: while
it charges, the power comes from the charger (mains, solar or alternator: the shunt can't tell
which); while it discharges, the power goes to the loads. Up to two Victron chargers can be added
(see flow_nodes): they get nodes of their own, and the loads can then be worked out.
"""
import math

import pygame

from . import gfx
from .victron import AUX_MIDPOINT, AUX_STARTER, AUX_TEMPERATURE, model_name

TEXT, MUTED, GOOD, WARN, BAD = "text", "muted", "good", "warn", "bad"
IDLE_W = 3       # below this many watts the battery counts as idle (no flow shown)


class State:
    def __init__(self):
        self.title = "SmartShunt"
        self.soc = self.time = "--"
        self.time_label = ""
        self.status = self.detail = ""
        self.soc_color = MUTED
        self.status_color = WARN
        self.bar = -1.0
        self.stale = True
        self.nodes = []                   # [Node] around the hub
        self.level = None                 # battery icon fill, %
        self.readings = []                # [(icon kind, icon colour key, label, value, value colour role)]


class Node:
    """One circle in the flow picture. `place`: top, left, right or bottom. `flow`: signed watts
    on its line, + toward the hub."""
    def __init__(self, place, color, icon, value, label, flow, extra="", extra_color=MUTED):
        self.place, self.color, self.icon = place, color, icon
        self.value, self.label, self.flow = value, label, flow
        self.extra, self.extra_color = extra, extra_color

    @property
    def active(self):
        return not math.isnan(self.flow) and abs(self.flow) > IDLE_W


class Dashboard:
    def __init__(self, strings, text, theme, u):
        self.t = strings
        self.txt = text
        self.c = theme
        self.u = u
        self.cog_hit = None
        self.status_hit = None
        self.cog_pressed = False

    # -------------------------------------------------------------- layout

    def draw(self, surf, st, now=0.0):
        W, H = surf.get_size()
        u, c = self.u, self.c
        surf.fill(c["bg"])
        m = g = 10 * u
        top = self._header(surf, st, W, m)
        if W >= H * 1.15:                              # landscape
            fw = (W - 2 * m - g) * 0.56
            flow = (m, top, fw, H - top - m)
            rx, rw = m + fw + g, W - 2 * m - fw - g
            bh = (H - top - m - g) * 0.36
            batt = (rx, top, rw, bh)
            info = (rx, top + bh + g, rw, H - top - m - bh - g)
        else:                                          # portrait
            avail = H - top - m - 2 * g
            fh, bh = avail * 0.5, avail * 0.19
            flow = (m, top, W - 2 * m, fh)
            batt = (m, top + fh + g, W - 2 * m, bh)
            info = (m, top + fh + bh + 2 * g, W - 2 * m, avail - fh - bh)
        r = 16 * u
        for card in (flow, batt, info):
            gfx.rrect(surf, card, r, c["panel"])
        self._flow(surf, flow, st, now)
        self._battery(surf, batt, st)
        self._readings(surf, info, st)

    def _header(self, surf, st, W, m):
        """Title on the left; status pill and cog on the right. Returns the top of the cards."""
        u, c, txt = self.u, self.c, self.txt
        hh = 44 * u
        mid = m + hh / 2
        ts = 22 * u
        # cog
        cr = 9 * u
        cx = W - m - cr * 1.6
        gfx.cog(surf, cx, mid, cr, c["text"] if self.cog_pressed else c["muted"], c["bg"])
        # status pill: dot, word, detail
        ws, ds = 15 * u, 13 * u
        word, detail = st.status, st.detail
        w_word = txt.width(word, ws, True)
        w_det = txt.width(detail, ds) if detail else 0
        pad, dot = 12 * u, 4 * u
        pw = pad + dot * 2 + 8 * u + w_word + (10 * u + w_det if detail else 0) + pad
        ph = 30 * u
        px = cx - cr * 2.4 - pw
        gfx.rrect(surf, (px, mid - ph / 2, pw, ph), ph / 2, c["panel"])
        x = px + pad
        gfx.circle(surf, x + dot, mid, dot, c[st.status_color])
        x += dot * 2 + 8 * u
        base = mid + txt.ascent(ws, True) * 0.36
        txt.draw(surf, word, x, base, ws, c[st.status_color], bold=True)
        if detail:
            txt.draw(surf, detail, x + w_word + 10 * u, base, ds, c["muted"])
        # title, in the space left of the pill
        tsz = txt.fit(st.title, px - m - 16 * u, ts, bold=True)
        txt.draw(surf, st.title, m + 4 * u, mid + txt.ascent(tsz, True) * 0.36, tsz, c["text"], bold=True)
        hs = max(44 * u, cr * 4)
        self.cog_hit = (W - m - hs, mid - hs / 2, hs + m, hs)
        self.status_hit = (px, mid - ph / 2, W - px, ph)
        return m + hh + 4 * u

    # -------------------------------------------------------------- energy flow

    def _flow(self, surf, rect, st, now):
        x, y, w, h = rect
        u, c, txt = self.u, self.c, self.txt
        pad = 14 * u
        R = min(w, h) * 0.105
        # With nothing on the left (no extra charger), the upright is moved a little left of
        # centre to balance the picture.
        has_left = any(n.place == "left" for n in st.nodes)
        cx, cy = x + w * (0.5 if has_left else 0.44), y + h / 2
        pos = dict(top=(cx, y + pad + R), bottom=(cx, y + h - pad - R),
                   left=(x + pad + R + 6 * u, cy), right=(x + w - pad - R - 6 * u, cy))
        hub = R * 0.42

        # lines, then the moving dots
        for n in st.nodes:
            nx, ny = pos[n.place]
            active = not st.stale and n.active
            dx, dy = cx - nx, cy - ny
            d = math.hypot(dx, dy)
            ux, uy = dx / d, dy / d
            a = (nx + ux * (R + 6 * u), ny + uy * (R + 6 * u))       # node edge
            b = (cx - ux * (hub + 6 * u), cy - uy * (hub + 6 * u))     # hub edge
            col = c[n.color]
            gfx.thick_line(surf, a, b, 4 * u, gfx.mix(col, c["panel"], 0.72) if active else c["line"])
            if active:
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                forward = n.flow > 0                                   # toward the hub
                speed = (26 + 22 * min(3.0, abs(n.flow) / 1000)) * u
                gap = 20 * u
                dd = (now * speed) % gap
                while dd < length:
                    t = dd if forward else length - dd
                    px, py = a[0] + ux * t, a[1] + uy * t
                    edge = min(dd, length - dd) / (6 * u)              # fade in and out at the ends
                    gfx.circle(surf, px, py, 3.2 * u * min(1.0, 0.35 + edge * 0.65), col)
                    dd += gap

        # hub
        gfx.circle(surf, cx, cy, hub + 2 * u, c["line"])
        gfx.circle(surf, cx, cy, hub, c["panel"])
        gfx.polygon(surf, gfx.bolt(cx, cy, hub * 1.24), c["muted"])

        # nodes and their labels
        vs, ls = 20 * u, 13 * u
        for n in st.nodes:
            nx, ny = pos[n.place]
            col = c[n.color]
            active = not st.stale and n.active
            tint = gfx.mix(col, c["panel"], 0.86)
            gfx.circle(surf, nx, ny, R, tint)
            gfx.ring(surf, nx, ny, R, 3 * u, col if active else gfx.mix(col, c["panel"], 0.55))
            gfx.icon(surf, n.icon, nx, ny, R * 1.05, col, tint, level=st.level if n.icon == "battery" else None)
            vcol = c["muted"] if st.stale or n.value == "--" else c["text"]
            ecol = c[n.extra_color]
            if n.place in ("top", "bottom"):        # beside the node: top on the right, bottom on the left
                right = n.place == "top"
                lx = nx + R + 12 * u if right else nx - R - 12 * u
                maxw = (x + w - pad - lx) if right else (lx - x - pad)
                anchor = "left" if right else "right"
                txt.draw(surf, n.value, lx, ny + vs * 0.1, txt.fit(n.value, maxw, vs, bold=True), vcol, bold=True, anchor=anchor)
                txt.draw(surf, n.label, lx, ny + vs * 0.1 + ls * 1.5, txt.fit(n.label, maxw, ls), c["muted"], anchor=anchor)
                if n.extra:
                    txt.draw(surf, n.extra, lx, ny + vs * 0.1 + ls * 2.85, txt.fit(n.extra, maxw, ls * 0.92), ecol,
                             anchor=anchor)
            elif n.place == "left":                  # above the node, clear of the battery's labels
                maxw = min(2 * (nx - x - 4 * u), R * 3.2)
                bottom = ny - R - 10 * u
                lb = bottom - (ls * 1.3 if n.extra else 0)
                if n.extra:
                    txt.draw(surf, n.extra, nx, bottom, txt.fit(n.extra, maxw, ls * 0.92), ecol, anchor="center")
                txt.draw(surf, n.label, nx, lb, txt.fit(n.label, maxw, ls), c["muted"], anchor="center")
                txt.draw(surf, n.value, nx, lb - ls * 1.45, txt.fit(n.value, maxw, vs, bold=True), vcol, bold=True,
                         anchor="center")
            else:                                                      # under the node
                maxw = min(2 * (nx - x - 4 * u), 2 * (x + w - 4 * u - nx), R * 3.2)
                base = ny + R + 12 * u + vs * 0.8
                txt.draw(surf, n.value, nx, base, txt.fit(n.value, maxw, vs, bold=True), vcol, bold=True, anchor="center")
                txt.draw(surf, n.label, nx, base + ls * 1.45, txt.fit(n.label, maxw, ls), c["muted"], anchor="center")
                if n.extra:
                    txt.draw(surf, n.extra, nx, base + ls * 2.8, txt.fit(n.extra, maxw, ls * 0.92), ecol, anchor="center")

    # -------------------------------------------------------------- state-of-charge card

    def _battery(self, surf, rect, st):
        x, y, w, h = rect
        u, c, txt = self.u, self.c, self.txt
        p = min(16 * u, h * 0.14)
        ls = min(14 * u, h * 0.13)
        txt.draw(surf, self.t("dash_soc"), x + p, y + p + txt.ascent(ls) * 0.8, txt.fit(self.t("dash_soc"), w * 0.5, ls), c["muted"])
        bar_h = max(8 * u, h * 0.1)
        bar_top = y + h - p - bar_h
        area_top, area_bottom = y + p + ls * 1.4, bar_top - p * 0.5
        col = c[st.soc_color]
        size = (area_bottom - area_top) * 0.98
        size = min(size, txt.fit(st.soc + "%", w * 0.5, size, bold=True))
        base = area_bottom - (-txt.font(size, True).get_descent()) * 0.25
        nw = txt.draw(surf, st.soc, x + p, base, size, col, bold=True)
        txt.draw(surf, "%", x + p + nw + 3 * u, base, size * 0.4, col, bold=True)
        rx = x + w * 0.52
        vs = txt.fit(st.time, x + w - p - rx, min(26 * u, (area_bottom - area_top) * 0.45), bold=True)
        txt.draw(surf, st.time, rx, base, vs, c["muted"] if st.stale else c["text"], bold=True)
        txt.draw(surf, st.time_label, rx, base - vs * 1.05, txt.fit(st.time_label, x + w - p - rx, ls), c["muted"])
        l, rt = x + p, x + w - p
        gfx.rrect(surf, (l, bar_top, rt - l, bar_h), bar_h / 2, c["track"])
        if st.bar > 0:
            gfx.rrect(surf, (l, bar_top, max((rt - l) * min(100, st.bar) / 100, bar_h), bar_h), bar_h / 2, col)

    # -------------------------------------------------------------- readings card

    def _readings(self, surf, rect, st):
        x, y, w, h = rect
        u, c, txt = self.u, self.c, self.txt
        p = min(16 * u, h * 0.08)
        ts = min(17 * u, h * 0.1)
        title_base = y + p + txt.ascent(ts, True) * 0.8
        title = self.t("dash_readings")
        txt.draw(surf, title, x + p, title_base, txt.fit(title, w - 2 * p, ts, True), c["text"], bold=True)
        gy = title_base + p * 0.6
        if w < 280 * u:                                # narrow card: one list, values on the right
            self._reading_list(surf, (x + p, gy, w - 2 * p, y + h - p * 0.5 - gy), st)
            return
        rows = 3
        rh = (y + h - p * 0.6 - gy) / rows
        cw = (w - 2 * p) / 2
        isz = min(22 * u, rh * 0.5)
        maxw = cw - isz - 18 * u
        # one text size for every cell, so the six values line up
        ls = min([min(13 * u, rh * 0.26)] + [txt.fit(r[2], maxw, min(13 * u, rh * 0.26)) for r in st.readings])
        vs = min([min(19 * u, rh * 0.36)] + [txt.fit(r[3], maxw, min(19 * u, rh * 0.36), bold=True) for r in st.readings])
        for i, (kind, ckey, label, value, vcol) in enumerate(st.readings):
            r, col = divmod(i, 2)
            cx0, cy0 = x + p + col * cw, gy + r * rh
            if r > 0 and col == 0:
                pygame.draw.line(surf, c["line"], (x + p, cy0), (x + w - p, cy0), max(1, int(u)))
            mid = cy0 + rh / 2
            self._reading_icon(surf, kind, ckey, cx0 + isz / 2 + 2 * u, mid, isz)
            tx = cx0 + isz + 12 * u
            txt.draw(surf, label, tx, mid - rh * 0.06, ls, c["muted"])
            txt.draw(surf, value, tx, mid + vs * 0.95, vs, c[vcol], bold=True)

    def _reading_icon(self, surf, kind, ckey, cx, cy, size):
        c = self.c
        if kind == "consumed":                         # a battery with a minus badge
            gfx.icon(surf, "battery", cx, cy, size, c[ckey], c["panel"], level=50)
            gfx.badge(surf, cx + size * 0.32, cy + size * 0.3, size * 0.22, c[ckey], c["panel"], plus=False)
        else:
            gfx.icon(surf, kind, cx, cy, size, c[ckey], c["panel"])

    def _reading_list(self, surf, rect, st):
        x, y, w, h = rect
        u, c, txt = self.u, self.c, self.txt
        rh = h / len(st.readings)
        isz = min(18 * u, rh * 0.62)
        size = min(15 * u, rh * 0.55)
        vw = max(txt.width(r[3], size, True) for r in st.readings)
        lw = w - isz - 10 * u - vw - 8 * u
        ls = min([size] + [txt.fit(r[2], lw, size) for r in st.readings])
        for i, (kind, ckey, label, value, vcol) in enumerate(st.readings):
            mid = y + i * rh + rh / 2
            base = mid + txt.ascent(size) * 0.36
            self._reading_icon(surf, kind, ckey, x + isz / 2, mid, isz)
            txt.draw(surf, label, x + isz + 10 * u, base, ls, c["muted"])
            txt.draw(surf, value, x + w, base, size, c[vcol], bold=True, anchor="right")


# ------------------------------------------------------------------ formatting

def fmt_power(t, w):
    """Watts without a sign: '456 W', '4.91 kW', '12.4 kW' (decimal comma where the language uses one)."""
    if w is None or math.isnan(w):
        return "--"
    a = int(abs(w) + 0.5)
    if a < 1000:
        return "%d W" % a
    if a < 9995:
        n = "%d.%02d" % divmod((a + 5) // 10, 100)
    else:
        n = "%d.%d" % divmod((a + 50) // 100, 10)
    if t.decimal_comma:
        n = n.replace(".", ",")
    return n + " kW"


def short_model(model_id):
    """Header title: 'SmartShunt', or the BMV's model ('BMV-712')."""
    name = model_name(model_id) or ""
    return name.split()[0] if name.startswith("BMV") else "SmartShunt"


_KINDS = dict(mains=("dash_mains", "charger"), solar=("dash_solar", "solar"), dcdc=("dash_dcdc", "car"))
_SOURCES = dict(auto=("dash_charger", "charger"), mains=("dash_mains", "charger"), solar=("dash_solar", "solar"),
                dcdc=("dash_dcdc", "car"), alternator=("dash_alternator", "car"))
_STAGES = {0: "stage_off", 1: "stage_off", 2: "stage_fault", 3: "stage_bulk", 4: "stage_absorption", 5: "stage_float",
           6: "stage_storage", 7: "stage_recondition", 11: "stage_psu", 245: "stage_starting",
           246: "stage_absorption", 247: "stage_recondition", 248: "stage_absorption"}


def stage_name(t, state):
    key = _STAGES.get(state)
    return t(key) if key else ""


def flow_nodes(t, pw, settings, chargers):
    """The charge sources and the loads.

    The shunt measures only the battery (pw, + charging). Each extra Victron charger reports its own
    output, so with K watts coming from them, the loads take K - pw when that's positive, and
    anything the battery gets beyond K came from a charger the display can't hear (shown on the
    "other" node). With no extra chargers this is the plain picture: charging comes from the
    charger, discharging goes to the loads."""
    known = not math.isnan(pw)
    extras, total = [], 0.0
    for slot, cr, problem in chargers:
        watts = cr.power if cr is not None and not problem else math.nan
        if not math.isnan(watts):
            watts = max(0.0, watts)
            total += watts
        label_key, icon = _KINDS.get(cr.kind if cr is not None else "", (None, "charger"))
        label = t(label_key) if label_key else t("charger_n", slot + 1)
        if problem:
            extra, ecol = t(dict(no_signal="st_no_signal", bad_key="st_bad_key", searching="st_searching")[problem]), WARN
        elif cr.error > 0:
            extra, ecol = t("charger_error", cr.error), BAD
        else:
            extra, ecol = stage_name(t, cr.state), MUTED
        extras.append((watts, icon, label, extra, ecol))
    if not extras:
        other = pw if known and pw > IDLE_W else 0.0
        loads = -pw if known and pw < -IDLE_W else 0.0
    else:
        other = max(0.0, pw - total)
        loads = max(0.0, total - pw)
    if not known:
        other = loads = math.nan

    nodes = []
    colors = ["accent", "charger"]
    places = ["left", "top"]
    for i, (watts, icon, label, extra, ecol) in enumerate(extras[:2]):
        nodes.append(Node(places[i], colors[i], icon, fmt_power(t, watts), label, watts, extra, ecol))
    if len(extras) < 2:
        key, icon = _SOURCES.get(settings.other_source, _SOURCES["auto"])
        if settings.other_source == "auto" and extras:      # not a plug: that's the mains charger's
            key, icon = "dash_other", "volt"
        label = t(key)
        nodes.append(Node("top", "charger", icon, fmt_power(t, other), label, other))
    icon = {"caravan": "caravan", "boat": "boat"}.get(getattr(settings, "loads_icon", "house"), "loads")
    nodes.append(Node("right", "loads", icon, fmt_power(t, loads), t("dash_loads"), -loads))
    return nodes


def build_state(t, reading, settings, now, last_heard, last_rssi, status, chargers=None):
    """Turns a reading into display strings and colours. `status` is (word, colour role, detail);
    `chargers` is the app's charger_info(): [(slot, ChargerReading or None, problem)]."""
    s = State()
    stale = last_heard == 0 or now - last_heard > settings.stale_after
    s.stale = stale
    r = reading
    s.title = short_model(r.model_id)

    def fmt(v, decimals, unit, sign=False):
        if v is None or math.isnan(v):
            return "--"
        n = "%.*f" % (decimals, v)
        if sign and v > 0 and not n.startswith("+"):
            n = "+" + n
        if n.startswith("-") and float(n) == 0:
            n = n[1:]
        if t.decimal_comma:
            n = n.replace(".", ",")
        return n + unit

    soc = r.soc
    s.soc = "--" if math.isnan(soc) else str(int(round(soc)))
    s.soc_color = (MUTED if stale or math.isnan(soc) else GOOD if soc >= settings.soc_amber
                   else WARN if soc >= settings.soc_red else BAD)
    s.bar = -1 if math.isnan(soc) else soc
    s.level = None if math.isnan(soc) else soc

    pw = r.power                                   # + charging, - discharging
    known = not math.isnan(pw)
    charging = known and pw > IDLE_W
    discharging = known and pw < -IDLE_W
    full = not math.isnan(soc) and soc >= 99.5

    # time left (the shunt's own estimate), or the battery's state
    if discharging:
        s.time_label = t("dash_time_left")
        m = r.remaining_mins
        if m < 0:
            s.time = "--"
        else:
            d, h, mm = m // 1440, (m % 1440) // 60, m % 60
            s.time = t("time_days_hours", d, h) if d > 0 else t("time_hours_minutes", h, mm)
    else:
        s.time_label = t("dash_battery")
        s.time = "--" if not known else t("time_full") if full else t("time_charging") if charging else t("time_idle")

    # flow picture: + toward the hub
    s.nodes = flow_nodes(t, pw, settings, chargers or [])
    s.nodes.append(Node("bottom", "battery", "battery", fmt_power(t, pw),
                        t("time_charging") if charging else t("dash_discharging") if discharging else t("dash_battery"),
                        -pw if known else math.nan, fmt(r.voltage, 2, " V")))

    # readings
    txt = MUTED if stale else TEXT
    cur = r.current
    cur_col = MUTED if stale or math.isnan(cur) else GOOD if cur > 0.05 else WARN if cur < -0.05 else TEXT
    if r.aux_mode == AUX_STARTER:
        aux = ("starter", "charger", t("dash_starter"), fmt(r.aux, 2, " V"), txt)
    elif r.aux_mode == AUX_MIDPOINT:
        aux = ("midpoint", "battery", t("dash_midpoint"), fmt(r.aux, 2, " V"), txt)
    elif r.aux_mode == AUX_TEMPERATURE:
        aux = ("temp", "accent", t("dash_temp"), fmt(r.aux, 0, " °C"), txt)
    else:
        aux = ("temp", "accent", t("dash_temp"), "--", MUTED)
    rssi = "%d dBm" % last_rssi if last_heard and last_rssi else "--"
    s.readings = [
        ("volt", "charger", t("dash_voltage"), fmt(r.voltage, 2, " V"), txt),
        ("amp", "loads", t("dash_current"), fmt(cur, 1, " A", True), cur_col),
        ("power", "accent", t("dash_power"), fmt(pw, 0, " W", True), cur_col),
        ("consumed", "battery", t("dash_consumed"), fmt(r.consumed_ah, 1, " Ah"), txt),
        aux,
        ("signal", "loads", t("dash_signal"), rssi, MUTED if rssi == "--" else txt),
    ]
    s.readings = [(k, ck, lb, v, MUTED if v == "--" else vc) for k, ck, lb, v, vc in s.readings]
    s.status, s.status_color, s.detail = status
    return s
