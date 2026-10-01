// Colours for the dashboard and settings screens (RGB565).
#pragma once
#include <Arduino_GFX_Library.h>

const uint16_t C_BG = RGB565(14, 17, 22), C_PANEL = RGB565(28, 33, 42), C_TEXT = RGB565(235, 238, 243),
               C_MUTED = RGB565(140, 150, 165), C_GREEN = RGB565(60, 200, 120),
               C_AMBER = RGB565(240, 180, 50), C_RED = RGB565(230, 70, 70), C_LINE = RGB565(42, 49, 60);

// Energy-flow colours: fixed hues, checked for colour-blind separation on the panel colour
// (the same as the Raspberry Pi and Android versions, and the AlphaESS display)
const uint16_t C_CHARGER = RGB565(0xC9, 0x85, 0x00), C_LOADS = RGB565(0x39, 0x87, 0xE5),
               C_BATTERY = RGB565(0x00, 0x83, 0x00), C_ACCENT = RGB565(0xD5, 0x51, 0x81);

// Colour a blended toward b by t (0 = a, 1 = b).
static inline uint16_t mix565(uint16_t a, uint16_t b, float t) {
  int ar = (a >> 11) & 31, ag = (a >> 5) & 63, ab = a & 31;
  int br = (b >> 11) & 31, bg = (b >> 5) & 63, bb = b & 31;
  int r = ar + (int)((br - ar) * t + (br >= ar ? 0.5f : -0.5f));
  int g = ag + (int)((bg - ag) * t + (bg >= ag ? 0.5f : -0.5f));
  int bl = ab + (int)((bb - ab) * t + (bb >= ab ? 0.5f : -0.5f));
  return (uint16_t)((r << 11) | (g << 5) | bl);
}
