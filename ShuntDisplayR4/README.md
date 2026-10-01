# SmartShunt display — Arduino UNO R4 WiFi + Jaycar XC4630 TFT shield

Same dashboard as the Raspberry Pi version, sized for the 320×240 shield. Settings can be changed on the touch screen (tap the cog). They're kept in the R4's built-in memory, and in `CONFIG.TXT` on the shield's SD card when there is one.

## 1. Libraries (Arduino IDE → Tools → Manage Libraries)
- **ArduinoBLE**
- **GFX Library for Arduino** (by Moon On Our Nation)
- **SD** (by Arduino; usually already installed)

(EEPROM, for the built-in memory, comes with the R4 board package.)

Board: **Arduino UNO R4 WiFi**.

## 2. Upload
Keep all the files in one folder called `ShuntDisplayR4`, open `ShuntDisplayR4.ino` and upload. You only need to do this once.

## 3. SD card
The card is optional. Settings are always saved in the R4's built-in memory, so they survive power-off without a card.

With a microSD card (FAT32, 32 GB or smaller) in the shield, settings are also saved to `CONFIG.TXT`, which you can edit on a computer:
- **Card with `CONFIG.TXT`:** the file is used, and copied into the built-in memory.
- **Blank card:** the display writes `CONFIG.TXT` from its current settings.
- **No card:** the built-in memory is used (or the defaults, if nothing has been saved yet).

## 4. Settings on the touch screen
**Tap the cog in the top-right corner.**

The very first time, the touch panel isn't calibrated yet, so tapping anywhere starts a calibration: tap the three crosses (a fingernail or stylus is most accurate). That's saved to the card and not asked again; after that, only the cog opens settings.

| Page | Settings |
|---|---|
| 1 | Shunt MAC and key (tap the row to type it on a hex keypad), rotation, demo data |
| 2 | Invert colours, "No signal" delay, amber and red charge levels |
| 3 | Recalibrate touch, screen-off timeout; shows the screen chip and touch pins that were found |
| 4 | Extra chargers (optional): MAC and key for up to two Victron chargers. To remove one, tap its MAC, then **Clear** and **OK** |
| 5 | What to call charging the extra chargers don't account for (Automatic, DC-DC, Solar, Mains, Alternator), and the Loads icon (House, Caravan, Boat) |

**Save** stores the settings (built-in memory, plus `CONFIG.TXT` if there's a card) and they take effect straight away. **Cancel**, or 90 seconds without a touch, goes back to the dashboard without changing anything.

To recalibrate the touch panel, hold the screen while powering on (or use page 3).

**Extra chargers:** a Victron Blue Smart IP22, SmartSolar MPPT or Orion XS with *Instant readout via Bluetooth* turned on can be added on page 4. It gets its own node on the left of the flow picture, with its output and charge stage, and the loads are worked out from it (see the [main README](../README.md#extra-victron-chargers)). With no extra chargers, the dashboard is the same as before.

**Updating from an earlier version:** settings saved in the built-in memory by an earlier version are kept.

**Screen timeout:** after 30 seconds without a touch the screen goes black (change it on page 3: Never, 15 s up to 10 min). Tap anywhere to wake it; that tap doesn't press anything. It also wakes by itself if the shunt raises an alarm. The XC4630's backlight is wired permanently on, so the screen goes dark rather than fully off.

## 5. Settings on a computer (optional)
You can also edit `CONFIG.TXT` directly. The MAC can be pasted as VictronConnect shows it, with or without colons. The key is 32 hex characters. Both come from VictronConnect → SmartShunt → ⚙ → ⋮ → Product info → Instant readout via Bluetooth → Show.

Extra chargers are `charger1_mac`, `charger1_key`, `charger2_mac` and `charger2_key`, and `other_source` is `auto`, `dcdc`, `solar`, `mains` or `alternator`. `loads_icon` is `house`, `caravan` or `boat`.

`lcd_chip` can only be changed in the file: `9341` for current XC4630 shields, `8230` for older batches. Delete the `touch_cal` line to force a recalibration.

## Troubleshooting
- **Touch does nothing:** open the Serial Monitor (115200) and press reset. It prints whether the touch panel was found and on which pins. If taps land in the wrong place, recalibrate.
- **Settings don't seem to apply:** the Serial Monitor also prints where the settings came from. "config error" in the status pill means a line in `CONFIG.TXT` wasn't understood.
- **All-white screen:** run the `XC4630_Test2` sketch; Part B shows which chip the shield has. If that test shows colours but the dashboard stays white, raise `R4BUS_WR_HOLD` in `Arduino_R4PAR8.h` (for example to 10).
- **"BLE fail" on the screen:** the display restarts the R4's radio chip once and keeps retrying every 15 seconds, while touch keeps working. If it never clears, unplug the R4 for a few seconds, and if that doesn't help, update the R4's radio firmware (IDE → Tools → Firmware Updater).
- **"Bad key":** the key doesn't match the shunt; enter it again.
- **"No signal":** the shunt hasn't been heard for the set time. Check the MAC and that Instant readout is still on (a shunt firmware update can turn it off).

## Pins
The screen uses D2–D9 and A0–A4 (the touch panel shares four of these). The SD card uses D10–D13.
