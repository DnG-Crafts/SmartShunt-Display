"""The app: reads the shunt, keeps the settings, runs the screens and the screen timeout."""
import math
import os
import time

import pygame

from . import ble, config, gfx, i18n, victron
from .dashboard import Dashboard, build_state, GOOD, WARN, BAD
from .display import Backlight, Screen
from .ui import Ctx, SettingsPage

SETTINGS_TIMEOUT_S = 90       # settings close by themselves if left untouched (like the Arduino display)
WATCHDOG_S = 60               # restart the Bluetooth scan if the shunt has been quiet this long
NEARBY_KEEP_S = 30            # "Find nearby" forgets devices not heard for this long
ANIMATION_FPS = 20            # the energy-flow dots; halved on a slow Pi (see run())


class ChargerSlot:
    """One extra charger: its settings and what was last heard from it."""

    def __init__(self):
        self.mac, self.key = "", None
        self.reading = None
        self.heard = self.bad_key = 0.0

    def configure(self, mac, key):
        new_key = victron.parse_key(key) if mac else None
        if (mac, new_key) != (self.mac, self.key):
            self.reading = None
            self.heard = self.bad_key = 0.0
        self.mac, self.key = (mac, new_key) if mac and key else ("", None)


class App:
    VERSION = "1.0"

    def __init__(self, config_path=None, window=None, demo=False, screen=None, scanner=None, backlight=None):
        self.config_path = config_path or config.default_path()
        self.settings, bad, existed = config.load(self.config_path)
        if not existed:
            try:
                config.save(self.settings, self.config_path)   # write a commented file to edit
            except OSError:
                pass
        self.bad_lines = bad
        self.force_demo = demo
        self.can_exit = window is not None or bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
        self.languages = i18n.available()
        self.screen = screen or Screen(window)
        self.backlight = backlight or Backlight()
        self.scanner = scanner or ble.Scanner()
        self.stack = []
        self.running = True

        self.reading = victron.Reading()
        self.key = None
        self.chargers = [ChargerSlot() for _ in range(config.CHARGER_SLOTS)]
        self.last_heard = 0.0
        self.last_rssi = 0
        self.last_bad_key = 0.0
        self.scan_restarted = time.monotonic()
        self.nearby = {}
        self.last_touch = time.monotonic()
        self.asleep = False
        self.swallow = False          # the tap that wakes the screen does nothing else
        self.dirty = True
        self._configure()

    # -------------------------------------------------------------- settings

    @property
    def demo(self):
        return self.force_demo or self.settings.demo

    def _configure(self):
        s = self.settings
        tag = s.language if s.language in self.languages[0] else i18n.system_language()
        self.strings = i18n.Strings(tag)
        self.text = gfx.Text(self.strings.tag)
        self.theme = gfx.LIGHT if s.theme == config.THEME_LIGHT else gfx.DARK
        self.screen.set_rotation(s.screen_rotation)
        W, H = self.screen.size()
        self.u = max(0.6, min(W, H) / 400)
        self.ctx = Ctx(self)
        self.dashboard = Dashboard(self.strings, self.text, self.theme, self.u)
        self.key = victron.parse_key(s.key)
        for i, c in enumerate(self.chargers):
            c.configure(s.charger_mac[i], s.charger_key[i])
        if self.backlight.available and not self.asleep:
            self.backlight.power(True, s.brightness)
        self.dirty = True

    def apply_settings(self, new):
        source_changed = (new.mac, new.key, new.demo) != (self.settings.mac, self.settings.key, self.settings.demo)
        self.settings = new
        try:
            config.save(new, self.config_path)
        except OSError as e:
            print("Couldn't save settings to %s: %s" % (self.config_path, e))
        if source_changed:
            self.reading = victron.Reading()
            self.last_heard = self.last_bad_key = 0.0
        self.stack = []
        self._configure()

    def duration_label(self, seconds):
        if seconds == 0:
            return self.strings("pi_never")
        if seconds < 60 or seconds % 60:
            return self.strings("seconds_value", seconds)
        return self.strings("pi_minutes_value", seconds // 60)

    # -------------------------------------------------------------- pages

    def push(self, page):
        self.stack.append(page)
        self.dirty = True

    def pop(self, n=1):
        del self.stack[-n:]
        self.dirty = True
        if not self.stack:     # back on the dashboard: settings may have changed live (brightness)
            self._configure()

    def quit(self):
        self.running = False

    # -------------------------------------------------------------- data

    def _on_advert(self, a):
        d = a.data
        if victron.is_battery_monitor(d) or (d and d[0] == 0x10):
            self.nearby[a.address] = dict(mac=a.address, name=a.name, rssi=a.rssi, time=a.time,
                                          model=victron.model_name(victron.model_id(d)),
                                          battery=victron.is_battery_monitor(d),
                                          charger=victron.CHARGER_KINDS.get(victron.record_type(d)))
        if self.demo:
            return
        for c in self.chargers:
            if c.mac and a.address == c.mac:
                res, cr = victron.decode_charger(d, c.key)
                if res == victron.OK:
                    c.reading, c.heard = cr, a.time
                    self.dirty = True
                elif res == victron.BAD_KEY:
                    c.bad_key = a.time
        if a.address != self.settings.mac:
            return
        res, r = victron.decode(d, self.key)
        if res == victron.OK:
            self.reading = r
            self.last_heard = a.time
            self.last_rssi = a.rssi
            self.dirty = True
        elif res == victron.BAD_KEY:
            self.last_bad_key = a.time

    def nearby_list(self, chargers=False):
        """Battery monitors in range, or with chargers=True the Victron chargers."""
        now = time.monotonic()
        found, others = [], 0
        kinds = dict(mains="charger_ac", solar="charger_solar", dcdc="charger_dcdc")
        for f in self.nearby.values():
            if now - f["time"] > NEARBY_KEEP_S:
                continue
            if not (f["charger"] if chargers else f["battery"]):
                others += 1
                continue
            if chargers:
                f = dict(f, model=self.strings(kinds[f["charger"]]))
            title = f["model"] or f["name"] or self.strings("victron_device")
            sub = "%s   %d dBm" % (f["mac"], f["rssi"])
            if f["name"] and f["model"]:
                sub = f["name"] + "   " + sub
            found.append(dict(mac=f["mac"], title=title, subtitle=sub, rssi=f["rssi"]))
        found.sort(key=lambda f: -f["rssi"])
        return found, others

    def nearby_status(self, others, chargers=False):
        st = self.scanner.state
        if st == ble.BT_OFF:
            return self.strings("bluetooth_off")
        if st in (ble.NO_ADAPTER, ble.FAILED, ble.NO_BLEAK):
            return self.strings("st_ble_fail") + ": " + (self.scanner.error or self.strings("pi_no_adapter_detail"))
        if chargers:
            return self.strings("scanning_chargers")
        if others:
            return self.strings.plural("scanning_others", others)
        return self.strings("scanning")

    def _demo_tick(self, now):
        t = now
        cur = -8.5 + 14 * math.sin(t / 20)
        r = victron.Reading()
        r.current = cur
        r.voltage = 13.1 + 0.02 * cur
        r.soc = 78.4 - (t / 60) % 20
        r.consumed_ah = -21.6
        r.remaining_mins = -1 if cur > 0 else 1234
        r.aux_mode, r.aux = victron.AUX_STARTER, 12.6
        self.reading = r
        self.last_heard = now
        self.last_rssi = -67
        # configured chargers: a mains charger that comes and goes, a solar charger with the sun
        for c in self.chargers:
            if not c.mac:
                continue
            kind = c.reading.kind if c.reading and c.reading.kind else "mains"
            cr = victron.ChargerReading(kind)
            cr.voltage = r.voltage
            watts = max(0.0, (400 if kind == "mains" else 180) * math.sin(t / (35 if kind == "mains" else 50)))
            cr.current = watts / cr.voltage
            cr.power = watts
            cr.state = 5 if 0 < watts < 150 else 3 if watts else 0
            cr.error = 0
            c.reading, c.heard = cr, now
            r.current += cr.current

    def status(self, now):
        t, s, sc = self.strings, self.settings, self.scanner
        stale = self.last_heard == 0 or now - self.last_heard > s.stale_after
        age = int(now - self.last_heard) if self.last_heard else 0
        if s.needs_setup() and not self.demo:
            return t("st_setup"), WARN, t("st_setup_detail")
        if self.demo:
            return t("st_ok"), GOOD, t("st_demo_detail")
        if sc.state == ble.NO_ADAPTER:
            return t("st_no_ble"), BAD, t("pi_no_adapter_detail")
        if sc.state == ble.NO_BLEAK:
            return t("st_ble_fail"), BAD, "python3-bleak"
        if sc.state == ble.BT_OFF:
            return t("st_bt_off"), WARN, t("pi_retrying")
        if sc.state == ble.FAILED:
            return t("st_ble_fail"), BAD, t("pi_retrying")
        if self.key is None or (self.last_bad_key and now - self.last_bad_key < 10 and stale):
            return t("st_bad_key"), BAD, t("st_bad_key_detail")
        if self.last_heard == 0:
            return t("st_searching"), WARN, ""
        if stale:
            return t("st_no_signal"), WARN, t("st_age_short", age)
        if self.reading.alarm:
            return t("st_alarm"), BAD, self.alarm_text(self.reading.alarm)
        return t("st_ok"), GOOD, t("st_age_short", age)

    def alarm_text(self, alarm):
        names = self.strings.array("alarm_names")
        active = [names[i] for i in range(len(names)) if alarm & (1 << i)]
        if not active:
            return self.strings("alarm_code", "0x%04X" % alarm)
        return active[0] + (" +%d" % (len(active) - 1) if len(active) > 1 else "")

    def charger_info(self, now):
        """The configured chargers for the dashboard: [(slot, ChargerReading or None, problem)],
        problem being "", "no_signal", "bad_key" or "searching"."""
        out = []
        for i, c in enumerate(self.chargers):
            if not c.mac:
                continue
            fresh = c.heard and now - c.heard <= self.settings.stale_after
            if fresh:
                out.append((i, c.reading, ""))
            elif c.key is None or (c.bad_key and now - c.bad_key < 10):
                out.append((i, c.reading, "bad_key"))
            else:
                out.append((i, c.reading, "no_signal" if c.heard else "searching"))
        return out

    def alarm_active(self, now):
        return (not self.demo and self.reading.alarm != 0 and self.last_heard
                and now - self.last_heard <= self.settings.stale_after)

    # -------------------------------------------------------------- screen timeout

    def sleep(self):
        self.asleep = True
        self.backlight.power(False)
        self.dirty = True

    def wake(self):
        self.asleep = False
        self.last_touch = time.monotonic()
        self.backlight.power(True, self.settings.brightness)
        self.dirty = True

    # -------------------------------------------------------------- loop

    def handle(self, ev):
        now = time.monotonic()
        kind = ev[0]
        if kind == "quit":
            self.running = False
            return
        if kind == "key":
            if ev[1] == pygame.K_ESCAPE:
                if self.stack:
                    self.pop()
                elif self.can_exit:
                    self.running = False
            return
        self.last_touch = now
        if self.asleep:
            if kind == "down":
                self.wake()
                self.swallow = True
            return
        if self.swallow:
            if kind == "up":
                self.swallow = False
            return
        self.dirty = True
        page = self.stack[-1] if self.stack else None
        if kind == "wheel":
            if page:
                page.wheel(ev[1])
            return
        x, y = ev[1], ev[2]
        if page:
            getattr(page, kind)(x, y)
            return
        # dashboard: the cog, or anywhere on the Status tile, opens settings
        d = self.dashboard
        hit = lambda r: r and r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]
        if kind == "down":
            d.cog_pressed = hit(d.cog_hit) or hit(d.status_hit)
        elif kind == "up":
            if d.cog_pressed and (hit(d.cog_hit) or hit(d.status_hit)):
                self.push(SettingsPage(self.ctx, self.settings))
            d.cog_pressed = False

    def tick(self, now):
        for a in self.scanner.drain():
            self._on_advert(a)
        if self.demo:
            self._demo_tick(now)
        s = self.settings
        # watchdog: BlueZ scans occasionally go quiet; restart if the shunt hasn't been heard
        if (not self.demo and not s.needs_setup() and self.scanner.state == ble.SCANNING
                and now - max(self.last_heard, self.scan_restarted) > WATCHDOG_S):
            self.scan_restarted = now
            self.scanner.restart()
        # settings left untouched: close them without saving
        if self.stack and now - self.last_touch > SETTINGS_TIMEOUT_S:
            self.stack = []
            self._configure()
        # screen timeout; an alarm wakes the screen
        if self.asleep and self.alarm_active(now):
            self.wake()
        elif (not self.asleep and not self.stack and s.screen_off > 0
              and now - self.last_touch > s.screen_off and not self.alarm_active(now)):
            self.sleep()
        for p in self.stack:
            if p.tick(now):
                self.dirty = True

    def draw(self, now):
        surf = self.screen.canvas
        if self.asleep:
            surf.fill((0, 0, 0))
        elif not self.stack:
            self.dashboard.draw(surf, build_state(self.strings, self.reading, self.settings, now,
                                                  self.last_heard, self.last_rssi, self.status(now),
                                                  self.charger_info(now)), now)
        else:
            # a confirm box is drawn over the page below it
            i = len(self.stack) - 1
            while i > 0 and getattr(self.stack[i], "overlay", False):
                i -= 1
            for p in self.stack[i:]:
                p.draw(surf)
        self.screen.present()

    def run(self):
        # systemctl stop (SIGTERM) and logging out (SIGHUP): finish the loop so the backlight is
        # switched back on, rather than being left off if the screen was asleep
        import signal
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, lambda *_: self.quit())
            except (ValueError, OSError):
                pass
        self.scanner.start()
        last_draw = 0.0
        fps = ANIMATION_FPS
        draw_ms = 0.0                 # recent average time to draw a frame
        try:
            while self.running:
                timeout = 1000 if self.asleep else 1000 // fps
                for ev in self.screen.events(timeout):
                    self.handle(ev)
                now = time.monotonic()
                self.tick(now)
                # the flow dots move while there's fresh data; otherwise a few redraws a second
                animating = not self.asleep and not self.stack and self.last_heard \
                    and now - self.last_heard <= self.settings.stale_after
                interval = 5.0 if self.asleep else 1.0 / fps if animating else 0.25
                if self.dirty or now - last_draw >= interval:
                    t0 = time.monotonic()
                    self.draw(now)
                    draw_ms = draw_ms * 0.9 + (time.monotonic() - t0) * 100     # smoothed, in ms
                    fps = ANIMATION_FPS if draw_ms < 15 else ANIMATION_FPS // 2
                    last_draw = now
                    self.dirty = False
        finally:
            self.scanner.stop()
            self.backlight.power(True, self.settings.brightness)
            if hasattr(self.screen, "close"):
                self.screen.close()
            pygame.quit()
