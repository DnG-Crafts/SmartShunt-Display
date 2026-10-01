"""Draws every screen off-screen (SDL's dummy video driver) in a few sizes and languages, and
checks taps reach the right places. Needs pygame; no screen or Bluetooth."""
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pygame  # noqa: F401
except ImportError:
    pygame = None


class FakeScanner:
    def __init__(self):
        from shuntdisplay import ble
        self.state, self.error, self.q = ble.SCANNING, "", []
    def start(self): pass
    def stop(self): pass
    def restart(self): pass
    def drain(self):
        q, self.q = self.q, []
        return q


class FakeBacklight:
    available = True
    def set_brightness(self, p): pass
    def power(self, on, p=100): pass


@unittest.skipIf(pygame is None, "pygame not installed")
class Screens(unittest.TestCase):
    def make(self, size, lang="", rotation=0):
        from shuntdisplay import app, config
        from shuntdisplay.display import Screen
        d = tempfile.mkdtemp()
        path = os.path.join(d, "CONFIG.TXT")
        s = config.Settings()
        s.language, s.screen_rotation, s.demo = lang, rotation, True
        config.save(s, path)
        return app.App(config_path=path, screen=Screen(size), scanner=FakeScanner(), backlight=FakeBacklight())

    def tap(self, a, rect):
        """A real tap: the screen is redrawn between finger down and finger up."""
        x, y, w, h = rect
        a.handle(("down", x + w / 2, y + h / 2))
        a.draw(time.monotonic())
        a.handle(("up", x + w / 2, y + h / 2))

    def row(self, page, key):
        for r in page.list.rows:
            if r.key == key:
                x, y, w, h = r.rect
                ay, ah = page.list.area[1], page.list.area[3]
                if not (page.list.offset <= y and y + h <= page.list.offset + ah):
                    page.list.offset = y          # scroll it into view, as a user would
                    page.list.clamp()
                return (x, ay + y - page.list.offset, w, h)
        raise AssertionError("no row %r" % (key,))

    def test_all_pages(self):
        from shuntdisplay import ble
        for size, lang, rot in (((800, 480), "", 0), ((480, 800), "de", 0), ((1280, 720), "ja", 0),
                                ((480, 320), "ru", 0), ((800, 480), "th", 90)):
            a = self.make(size, lang, rot)
            now = time.monotonic()
            a.tick(now); a.draw(now)
            self.tap(a, a.dashboard.cog_hit)
            self.assertEqual(len(a.stack), 1, (size, lang))
            sp = a.stack[0]
            a.draw(now)
            a.scanner.q = [ble.Advert("E8:1F:4A:92:C6:0D", "House", bytes.fromhex(
                "100289a302b040af925d09a4d89aa0128bdef48c6298a9"), -58)]
            for open_page in (sp.edit_mac, sp.edit_key, sp.pick_language, sp.pick_theme, sp.pick_rotation,
                              sp.pick_screen_off, sp.edit_brightness, sp.edit_stale, sp.find_nearby):
                open_page()
                a.tick(now); a.draw(now)
                a.pop()
            # typing on the keypad
            sp.edit_mac(); a.draw(now)
            kp = a.stack[-1]
            for ch in "c03b12345678":
                self.tap(a, kp.keys[int(ch, 16)].rect)
            self.tap(a, kp.right.rect)
            self.assertEqual(sp.s.mac, "c0:3b:12:34:56:78")
            # list rows respond to taps (rows are rebuilt on every redraw)
            a.draw(now)
            self.tap(a, self.row(sp, ("toggle", sp.t("demo_label"))))
            self.assertFalse(sp.s.demo)
            self.tap(a, self.row(sp, ("value", sp.t("pi_rotation_label"))))
            a.draw(now)
            self.tap(a, self.row(a.stack[-1], ("choice", 180)))
            self.assertEqual(sp.s.screen_rotation, 180)
            sp.find_nearby(); a.tick(now); a.draw(now)
            self.tap(a, self.row(a.stack[-1], ("device", "e8:1f:4a:92:c6:0d")))
            self.assertEqual(sp.s.mac, "e8:1f:4a:92:c6:0d")
            sp.save()
            self.assertEqual(a.stack, [])
            self.assertEqual(a.settings.mac, "e8:1f:4a:92:c6:0d")
            self.assertEqual(a.settings.screen_rotation, 180)


if __name__ == "__main__":
    unittest.main()
