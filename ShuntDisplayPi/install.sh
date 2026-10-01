#!/bin/bash
# Installs Shunt Display on Raspberry Pi OS.
#
#   sudo bash install.sh              dedicated display: starts at boot, full screen, no desktop
#   sudo bash install.sh --desktop    starts when you log in to the Raspberry Pi desktop
#   sudo bash install.sh --uninstall  removes it (your settings file is kept)
set -e

APP_DIR=/opt/shunt-display
SERVICE=/etc/systemd/system/shunt-display.service
UDEV_RULE=/etc/udev/rules.d/90-shunt-display-backlight.rules
SRC="$(cd "$(dirname "$0")" && pwd)"
MODE=kiosk
case "$1" in
  --desktop) MODE=desktop ;;
  --uninstall) MODE=uninstall ;;
  ""|--kiosk) ;;
  *) echo "Usage: sudo bash install.sh [--desktop | --uninstall]"; exit 1 ;;
esac

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo bash install.sh $*"
  exit 1
fi
USER_NAME="${SUDO_USER:-}"
USER_HOME=""
[ -n "$USER_NAME" ] && USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
if [ "$MODE" = desktop ] && [ -z "$USER_HOME" ]; then
  echo "For --desktop, run this with sudo from the account that logs in to the desktop."
  exit 1
fi
AUTOSTART="$USER_HOME/.config/autostart/shunt-display.desktop"

if [ "$MODE" = uninstall ]; then
  systemctl disable --now shunt-display.service 2>/dev/null || true
  rm -f "$SERVICE" "$UDEV_RULE"
  [ -n "$USER_HOME" ] && rm -f "$AUTOSTART"
  systemctl daemon-reload
  rm -rf "$APP_DIR"
  echo "Removed. Settings files were left in place:"
  echo "  /boot/firmware/shunt-display.txt and ~/.config/shunt-display/CONFIG.TXT"
  exit 0
fi

echo "== Installing packages (this can take a few minutes)"
apt-get update
# fonts-noto-* let the app show every language's script (Japanese, Thai, Hindi, ...)
apt-get install -y python3 python3-pygame bluez rfkill fontconfig \
  fonts-dejavu-core fonts-noto-core fonts-noto-cjk
if ! apt-get install -y python3-bleak; then
  echo "python3-bleak isn't packaged here; installing it with pip instead"
  apt-get install -y python3-pip
  pip3 install --break-system-packages bleak
fi
rfkill unblock bluetooth 2>/dev/null || true
# The graphics drivers pygame needs to draw full screen without a desktop. Raspberry Pi OS Lite
# doesn't include them, and without them the display fails with "EGL not initialized".
apt-get install -y libgl1-mesa-dri libegl-mesa0 libgbm1 || \
  echo "Warning: couldn't install the graphics drivers (libgl1-mesa-dri libegl-mesa0 libgbm1)"

echo "== Copying the app to $APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$SRC/shunt_display.py" "$SRC/shuntdisplay" "$APP_DIR/"
find "$APP_DIR" -name __pycache__ -prune -exec rm -rf {} +
chmod 755 "$APP_DIR/shunt_display.py"

if [ "$MODE" = kiosk ]; then
  echo "== Setting up the service (starts at boot, full screen)"
  cat > "$SERVICE" <<EOF
[Unit]
Description=Shunt Display (Victron SmartShunt screen)
After=bluetooth.target systemd-user-sessions.service
Wants=bluetooth.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/usr/bin/python3 $APP_DIR/shunt_display.py
EnvironmentFile=-/etc/default/locale
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=3
RuntimeDirectory=shunt-display
Environment=XDG_RUNTIME_DIR=/run/shunt-display

[Install]
WantedBy=multi-user.target
EOF
  [ -n "$USER_HOME" ] && rm -f "$AUTOSTART"
  systemctl daemon-reload

  if [ "$(systemctl get-default)" = graphical.target ]; then
    # The desktop would fight the display for the screen, so only enable the service once the
    # Pi starts to the console.
    echo
    echo "This Pi starts the desktop, which takes over the screen. For a dedicated display"
    echo "it should start to the console instead (you can change this back with raspi-config)."
    ans=n
    if [ -t 0 ]; then
      read -r -p "Start to the console from now on? [Y/n] " ans || ans=n
      [ -z "$ans" ] && ans=y
    fi
    if [ "${ans,,}" = y ] || [ "${ans,,}" = yes ]; then
      systemctl set-default multi-user.target
      systemctl enable shunt-display.service
      echo "Done. Reboot to start the display: sudo reboot"
    else
      systemctl disable shunt-display.service 2>/dev/null || true
      echo "Not enabled, because the desktop would take over the screen. Either:"
      echo "  - switch to the console (sudo raspi-config > System Options > Boot) and run this again, or"
      echo "  - run inside the desktop instead: sudo bash install.sh --desktop"
    fi
    exit 0
  fi
  systemctl enable shunt-display.service
  systemctl restart shunt-display.service
  echo
  echo "Installed. The display is starting now, and will start at every boot."
  echo "Settings file: /boot/firmware/shunt-display.txt (or tap the cog on the screen)"
  echo "Log: journalctl -u shunt-display -f"
else
  echo "== Setting up autostart for $USER_NAME's desktop"
  systemctl disable --now shunt-display.service 2>/dev/null || true
  rm -f "$SERVICE"
  systemctl daemon-reload
  mkdir -p "$(dirname "$AUTOSTART")"
  cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Shunt Display
Comment=Victron SmartShunt screen
Exec=/usr/bin/python3 $APP_DIR/shunt_display.py
X-GNOME-Autostart-enabled=true
EOF
  chown -R "$USER_NAME": "$USER_HOME/.config"
  # Let the app switch the screen's backlight off and on (screen timeout, brightness)
  cat > "$UDEV_RULE" <<'EOF'
SUBSYSTEM=="backlight", RUN+="/bin/chmod 666 /sys%p/brightness /sys%p/bl_power"
EOF
  udevadm control --reload-rules && udevadm trigger --subsystem-match=backlight || true
  usermod -a -G bluetooth "$USER_NAME" || true
  echo
  echo "Installed. It will start the next time $USER_NAME logs in to the desktop."
  echo "To start it now: python3 $APP_DIR/shunt_display.py   (Esc closes it)"
  echo "Settings file: $USER_HOME/.config/shunt-display/CONFIG.TXT (or tap the cog on the screen)"
fi
