"""Drawing without pygame's own screen output: straight to the Linux framebuffer (/dev/fbN),
with touch read from the input devices (/dev/input/event*).

Used when pygame can't open the screen itself (it needs working EGL graphics, which some
screens and setups don't have). The app draws into an ordinary pygame surface as usual, and
each frame is copied to the framebuffer.
"""
import fcntl
import glob
import mmap
import os
import select
import struct

# ---------------------------------------------------------------- framebuffer


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def find_framebuffer():
    """The framebuffer to draw on: SHUNT_FB if set, else the last one (a small SPI screen
    is usually fb1, with the HDMI output as fb0), else None."""
    want = os.environ.get("SHUNT_FB")
    if want:
        return want
    fbs = sorted(glob.glob("/dev/fb[0-9]*"), key=lambda p: int(p[len("/dev/fb"):]))
    return fbs[-1] if fbs else None


def fb_geometry(dev):
    """(width, height, bits_per_pixel, stride) from sysfs."""
    sysd = "/sys/class/graphics/" + os.path.basename(dev)
    bpp = int(_read(sysd + "/bits_per_pixel", "16"))
    w = h = 0
    mode = _read(sysd + "/modes").splitlines()          # e.g. "U:800x480p-0"
    if mode and ":" in mode[0]:
        try:
            size = mode[0].split(":", 1)[1].split("p")[0].split("i")[0]
            w, h = (int(v) for v in size.split("x"))
        except ValueError:
            w = h = 0
    if not w:
        w, h = (int(v) for v in _read(sysd + "/virtual_size", "0,0").split(","))
    stride = int(_read(sysd + "/stride", "0")) or w * bpp // 8
    return w, h, bpp, stride


class Framebuffer:
    def __init__(self, dev, pygame):
        self.pg = pygame
        self.dev = dev
        self.W, self.H, self.bpp, self.stride = fb_geometry(dev)
        if not self.W or not self.H or self.bpp not in (16, 24, 32):
            raise OSError("unsupported framebuffer %s: %sx%s, %s bits" % (dev, self.W, self.H, self.bpp))
        self.f = open(dev, "r+b", buffering=0)
        self.mm = mmap.mmap(self.f.fileno(), self.stride * self.H)
        masks = {16: (0xF800, 0x07E0, 0x001F, 0)}.get(self.bpp, (0xFF0000, 0x00FF00, 0x0000FF, 0))
        self.out = pygame.Surface((self.W, self.H), 0, self.bpp, masks)
        self.row = self.W * self.bpp // 8
        self._console(graphics=True)

    def show(self, surface):
        self.out.blit(surface, (0, 0))
        data = self.out.get_buffer().raw
        pitch = self.out.get_pitch()
        if pitch == self.stride:
            self.mm[:len(data)] = data
        else:
            for y in range(self.H):
                self.mm[y * self.stride:y * self.stride + self.row] = data[y * pitch:y * pitch + self.row]

    def _console(self, graphics):
        """Stops the text console (login prompt, cursor) drawing over the picture."""
        KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0, 1
        try:
            fd = os.open("/dev/tty0", os.O_RDWR)
            try:
                fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS if graphics else KD_TEXT)
            finally:
                os.close(fd)
        except OSError:
            pass

    def close(self):
        self._console(graphics=False)
        try:
            self.mm.close()
            self.f.close()
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------- touch

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BTN_TOUCH, BTN_LEFT = 0x14A, 0x110
ABS_X, ABS_Y, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x00, 0x01, 0x35, 0x36, 0x39
EVENT = struct.Struct("llHHi")      # struct input_event: time (2 longs), type, code, value


def _bits(text):
    """A sysfs capability bitmap ("3 0 0" style, highest word first) -> int."""
    n = 0
    for word in text.split():
        n = (n << (struct.calcsize("l") * 8)) | int(word, 16)
    return n


def _absinfo(fd, code):
    """(min, max) of an absolute axis (ioctl EVIOCGABS)."""
    size = 24
    req = (2 << 30) | (size << 16) | (ord("E") << 8) | (0x40 + code)
    buf = fcntl.ioctl(fd, req, bytes(size))
    _, lo, hi, _, _, _ = struct.unpack("6i", buf)
    return lo, hi


class Touch:
    """Reads every touch screen found; reports ("down"|"move"|"up", x, y) in screen pixels."""

    def __init__(self, width, height):
        self.W, self.H = width, height
        self.devs = []
        for ev in sorted(glob.glob("/sys/class/input/event*")):
            absbits = _bits(_read(ev + "/device/capabilities/abs", "0"))
            if not (absbits >> ABS_X & 1 and absbits >> ABS_Y & 1):
                continue
            try:
                fd = os.open("/dev/input/" + os.path.basename(ev), os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            mt = absbits >> ABS_MT_POSITION_X & 1 and absbits >> ABS_MT_POSITION_Y & 1
            try:
                xr = _absinfo(fd, ABS_MT_POSITION_X if mt else ABS_X)
                yr = _absinfo(fd, ABS_MT_POSITION_Y if mt else ABS_Y)
            except OSError:
                os.close(fd)
                continue
            self.devs.append(dict(fd=fd, mt=mt, xr=xr, yr=yr, x=0, y=0, down=False, was=False, moved=False,
                                  name=_read(ev + "/device/name")))

    def names(self):
        return [d["name"] for d in self.devs]

    def _scale(self, v, rng, size):
        lo, hi = rng
        if hi <= lo:
            return v
        return max(0, min(size - 1, (v - lo) * (size - 1) // (hi - lo)))

    def read(self, timeout_s):
        fds = [d["fd"] for d in self.devs]
        if not fds:
            select.select([], [], [], timeout_s)
            return []
        ready, _, _ = select.select(fds, [], [], timeout_s)
        out = []
        for d in self.devs:
            if d["fd"] not in ready:
                continue
            try:
                data = os.read(d["fd"], EVENT.size * 64)
            except BlockingIOError:
                continue
            except OSError:
                continue
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, typ, code, val = EVENT.unpack_from(data, i)
                if typ == EV_ABS:
                    if code in ((ABS_MT_POSITION_X,) if d["mt"] else (ABS_X,)):
                        d["x"] = self._scale(val, d["xr"], self.W); d["moved"] = True
                    elif code in ((ABS_MT_POSITION_Y,) if d["mt"] else (ABS_Y,)):
                        d["y"] = self._scale(val, d["yr"], self.H); d["moved"] = True
                    elif code == ABS_MT_TRACKING_ID:
                        d["down"] = val >= 0
                elif typ == EV_KEY and code in (BTN_TOUCH, BTN_LEFT):
                    d["down"] = val != 0
                elif typ == EV_SYN and code == 0:
                    if d["down"] and not d["was"]:
                        out.append(("down", d["x"], d["y"]))
                    elif d["down"] and d["moved"]:
                        out.append(("move", d["x"], d["y"]))
                    elif not d["down"] and d["was"]:
                        out.append(("up", d["x"], d["y"]))
                    d["was"], d["moved"] = d["down"], False
        return out
