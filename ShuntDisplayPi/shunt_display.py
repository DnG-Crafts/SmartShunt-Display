#!/usr/bin/env python3
"""Shunt Display for Raspberry Pi.

Shows live readings from a Victron SmartShunt (or BMV-712) on a touch screen, from the shunt's
Bluetooth "Instant Readout" broadcasts. Set it up on the screen: tap the cog.

    python3 shunt_display.py                  full screen
    python3 shunt_display.py --window 800x480 in a window (on a desktop)
    python3 shunt_display.py --demo           fake readings, to try the screen
    python3 shunt_display.py --config FILE    use another settings file
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    p = argparse.ArgumentParser(description="Victron SmartShunt display for Raspberry Pi")
    p.add_argument("--config", help="settings file (default: /boot/firmware/shunt-display.txt when "
                                    "run as root, otherwise ~/.config/shunt-display/CONFIG.TXT)")
    p.add_argument("--window", metavar="WxH", help="run in a window of this size instead of full screen")
    p.add_argument("--demo", action="store_true", help="show fake readings (not saved)")
    a = p.parse_args()
    window = None
    if a.window:
        try:
            w, h = a.window.lower().split("x")
            window = (int(w), int(h))
        except ValueError:
            p.error("--window must look like 800x480")
    from shuntdisplay.app import App
    App(config_path=a.config, window=window, demo=a.demo).run()


if __name__ == "__main__":
    main()
