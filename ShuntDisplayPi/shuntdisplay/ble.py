"""Bluetooth: listens for Victron advertisements with bleak (BlueZ) in a background thread.

Every Victron advertisement is passed on (the app picks out its shunt, and "Find nearby" lists
them all), so one scan serves both. Instant Readout needs no pairing or connection.
"""
import asyncio
import queue
import shutil
import subprocess
import threading
import time

from .victron import VICTRON_COMPANY_ID

RETRY_S = 15

# Scanner states, as shown on the dashboard
STARTING, SCANNING, NO_ADAPTER, BT_OFF, FAILED, NO_BLEAK = "starting", "scanning", "no_adapter", "bt_off", "failed", "no_bleak"


class Advert:
    __slots__ = ("address", "name", "data", "rssi", "time")

    def __init__(self, address, name, data, rssi):
        self.address = address.lower()
        self.name = name
        self.data = data
        self.rssi = rssi
        self.time = time.monotonic()


class Scanner:
    """Runs in its own thread. Read adverts with drain(); state and error are plain attributes."""

    def __init__(self):
        self.adverts = queue.Queue(maxsize=500)
        self.state = STARTING
        self.error = ""
        self._loop = None
        self._restart = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="ble", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True
        self.restart()

    def restart(self):
        """Stops and starts the scan again (a watchdog for BlueZ scans that go quiet)."""
        if self._loop and self._restart:
            self._loop.call_soon_threadsafe(self._restart.set)

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.adverts.get_nowait())
            except queue.Empty:
                return out

    # -------------------------------------------------------------- thread

    def _run(self):
        try:
            import bleak  # noqa: F401
        except ImportError:
            self.state, self.error = NO_BLEAK, "bleak not installed"
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    def _on_advert(self, device, adv):
        data = adv.manufacturer_data.get(VICTRON_COMPANY_ID)
        if not data:
            return
        rssi = getattr(adv, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", 0) or 0
        try:
            self.adverts.put_nowait(Advert(device.address, adv.local_name or device.name, bytes(data), rssi))
        except queue.Full:
            pass

    async def _main(self):
        from bleak import BleakScanner
        self._restart = asyncio.Event()
        tried_power_on = False
        while not self._stop:
            self._restart.clear()
            scanner = None
            try:
                scanner = BleakScanner(detection_callback=self._on_advert, scanning_mode="active")
                await scanner.start()
                self.state, self.error = SCANNING, ""
                tried_power_on = False
                await self._restart.wait()
            except Exception as e:  # bleak raises several types; sort them by message
                msg = "%s: %s" % (type(e).__name__, e)
                low = msg.lower()
                if "no bluetooth adapter" in low or "adapter not found" in low or "not found" in low and "adapter" in low:
                    self.state = NO_ADAPTER
                elif "notready" in low or "not ready" in low or "powered" in low or "rfkill" in low or "blocked" in low:
                    self.state = BT_OFF
                    if not tried_power_on:
                        tried_power_on = True
                        await asyncio.get_running_loop().run_in_executor(None, power_on)
                else:
                    self.state = FAILED
                self.error = msg[:200]
                try:
                    await asyncio.wait_for(self._restart.wait(), RETRY_S if self.state != BT_OFF else 5)
                except asyncio.TimeoutError:
                    pass
            finally:
                if scanner is not None and self.state == SCANNING:
                    try:
                        await scanner.stop()
                    except Exception:
                        pass
            if not self._stop and self.state == SCANNING:
                self.state = STARTING


def power_on():
    """Tries to switch Bluetooth on: unblock it (rfkill) and power the adapter up (bluetoothctl)."""
    for cmd in (["rfkill", "unblock", "bluetooth"], ["bluetoothctl", "power", "on"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
