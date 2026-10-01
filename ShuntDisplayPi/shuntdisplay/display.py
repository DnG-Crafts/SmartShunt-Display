"""The screen: full-screen pygame window, rotation, touch/mouse input and the backlight."""
import glob
import os

import pygame


class Screen:
    def __init__(self, window_size=None):
        pygame.display.init()
        pygame.font.init()
        self.fb = self.touch = None
        if window_size:
            self.surface = pygame.display.set_mode(window_size)
            self.fullscreen = False
        else:
            self.surface = self._open_fullscreen() or self._open_framebuffer()
            self.fullscreen = True
            pygame.mouse.set_visible(False)
        pygame.display.set_caption("Shunt Display")
        self.W, self.H = self.surface.get_size()
        self.rotation = 0
        self.canvas = self.surface

    @staticmethod
    def _open_fullscreen():
        """Full screen. Without a desktop, pygame draws straight to the screen (KMS/DRM). A Pi can
        have more than one graphics device (/dev/dri/card0, card1...) and the first one pygame
        picks isn't always the one with the screen, so if it fails, each is tried in turn."""
        try:
            return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        except pygame.error as e:
            first = e
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("SDL_VIDEODRIVER"):
            raise first
        cards = sorted(int(p[len("/dev/dri/card"):]) for p in glob.glob("/dev/dri/card*")
                       if p[len("/dev/dri/card"):].isdigit())
        for i in cards:
            pygame.display.quit()
            os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
            os.environ["SDL_KMSDRM_DEVICE_INDEX"] = str(i)
            try:
                pygame.display.init()
                surf = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                print("Screen: /dev/dri/card%d" % i, flush=True)
                return surf
            except pygame.error:
                continue
        print("Can't draw on the screen directly (%s): using the framebuffer instead" % first, flush=True)
        return None

    def _open_framebuffer(self):
        from . import fbscreen
        dev = fbscreen.find_framebuffer()
        if not dev:
            raise SystemExit("Can't open the screen: pygame can't, and there's no framebuffer (/dev/fb0)")
        pygame.display.quit()
        os.environ["SDL_VIDEODRIVER"] = "dummy"          # draw off-screen; frames are copied to dev
        pygame.display.init()
        try:
            self.fb = fbscreen.Framebuffer(dev, pygame)
        except OSError as e:
            raise SystemExit("Can't open the screen: %s" % e)
        surf = pygame.display.set_mode((self.fb.W, self.fb.H))
        self.touch = fbscreen.Touch(self.fb.W, self.fb.H)
        print("Screen: framebuffer %s, %dx%d, %d bits; touch: %s" % (
            dev, self.fb.W, self.fb.H, self.fb.bpp, ", ".join(self.touch.names()) or "none found"), flush=True)
        return surf

    def close(self):
        if self.fb:
            self.fb.close()

    def set_rotation(self, degrees):
        self.rotation = degrees % 360
        if self.rotation == 0:
            self.canvas = self.surface
        else:
            size = (self.W, self.H) if self.rotation == 180 else (self.H, self.W)
            self.canvas = pygame.Surface(size)

    def size(self):
        return self.canvas.get_size()

    def present(self):
        if self.canvas is not self.surface:
            # pygame rotates anticlockwise for positive angles; our rotation is clockwise
            self.surface.blit(pygame.transform.rotate(self.canvas, -self.rotation), (0, 0))
        if self.fb:
            self.fb.show(self.surface)
        else:
            pygame.display.flip()

    def to_canvas(self, px, py):
        """Physical screen position -> position on the (rotated) canvas."""
        W, H = self.W, self.H
        if self.rotation == 90:
            return py, W - 1 - px
        if self.rotation == 180:
            return W - 1 - px, H - 1 - py
        if self.rotation == 270:
            return H - 1 - py, px
        return px, py

    def events(self, timeout_ms):
        """Waits up to timeout_ms, then returns input as ("down"|"move"|"up", x, y) on the canvas,
        plus ("quit",) and ("key", key). Touch screens and mice both work."""
        if self.touch:
            return [(k,) + self.to_canvas(x, y) for k, x, y in self.touch.read(timeout_ms / 1000)]
        out = []
        ev = pygame.event.wait(timeout_ms)
        evs = [ev] + pygame.event.get() if ev.type != pygame.NOEVENT else pygame.event.get()
        for e in evs:
            if e.type == pygame.QUIT:
                out.append(("quit",))
            elif e.type == pygame.KEYDOWN:
                out.append(("key", e.key))
            elif e.type in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
                kind = {pygame.FINGERDOWN: "down", pygame.FINGERMOTION: "move", pygame.FINGERUP: "up"}[e.type]
                out.append((kind,) + self.to_canvas(e.x * self.W, e.y * self.H))
            elif e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                if getattr(e, "touch", False):
                    continue            # the same touch also arrives as FINGER events
                if e.type == pygame.MOUSEMOTION:
                    if not e.buttons[0]:
                        continue
                    kind = "move"
                elif getattr(e, "button", 1) != 1:
                    continue            # right button, and the wheel (it also arrives as MOUSEWHEEL)
                else:
                    kind = "down" if e.type == pygame.MOUSEBUTTONDOWN else "up"
                out.append((kind,) + self.to_canvas(*e.pos))
            elif e.type == pygame.MOUSEWHEEL:
                out.append(("wheel", -e.y))
        return out


class Backlight:
    """Controls /sys/class/backlight (official DSI displays and many others). HDMI screens
    usually have no backlight control; then the screen is blanked to black instead."""

    def __init__(self):
        self.path = None
        self.max = 0
        for p in sorted(glob.glob("/sys/class/backlight/*")):
            try:
                with open(os.path.join(p, "max_brightness")) as f:
                    mx = int(f.read().strip())
                if mx > 0 and os.access(os.path.join(p, "brightness"), os.W_OK):
                    self.path, self.max = p, mx
                    break
            except (OSError, ValueError):
                continue

    @property
    def available(self):
        return self.path is not None

    def _write(self, name, value):
        try:
            with open(os.path.join(self.path, name), "w") as f:
                f.write(str(value))
            return True
        except OSError:
            return False

    def set_brightness(self, percent):
        if self.path:
            self._write("brightness", max(1, round(self.max * percent / 100)))

    def power(self, on, percent=100):
        """Switches the backlight off (screen timeout) or back on."""
        if not self.path:
            return
        if os.path.exists(os.path.join(self.path, "bl_power")):
            self._write("bl_power", 0 if on else 4)
        if on:
            self.set_brightness(percent)
        else:
            self._write("brightness", 0)
