// UC8230 driver for Arduino_GFX (8-bit parallel "MCUFriend" shield on Uno R4).
// Init sequence and orientation logic ported from MCUFRIEND_kbv (David Prentice).
#pragma once
#include <Arduino_GFX_Library.h>

class Arduino_UC8230 : public Arduino_TFT {
public:
  Arduino_UC8230(Arduino_DataBus *bus, int8_t rst = A4, uint8_t r = 1)
      : Arduino_TFT(bus, rst, r, false, 240, 320, 0, 0, 0, 0) {}

  bool begin(int32_t speed = GFX_NOT_DEFINED) override { return Arduino_TFT::begin(speed); }

  void setRotation(uint8_t r) override {
    Arduino_TFT::setRotation(r);
    // MADCTL-style value per rotation, then the UC8230 quirks (INVERT_GS, INVERT_RGB,
    // and swapped BGR in rotations 1 and 2), exactly as MCUFRIEND_kbv does it.
    static const uint8_t base[4] = {0x48, 0x28, 0x98, 0xF8};
    const uint8_t r4 = _rotation & 3;
    uint8_t val = base[r4] ^ 0x80 ^ 0x08;
    if (r4 == 1 || r4 == 2) val ^= 0x08;

    _bus->beginWrite();
    reg(0x60, (val & 0x80 ? 0x8000 : 0) | 0x2700);  // gate scan direction (GS)
    reg(0x01, (val & 0x40) ? 0x0100 : 0);           // source scan direction (SS)
    reg(0x03, (val & 0x08 ? 0x1000 : 0) | (val & 0x20 ? 0x0008 : 0) | 0x0030);  // BGR, AM, ID
    _bus->endWrite();
    _swap = (_rotation & 1);  // landscape: x/y go to swapped GRAM registers
  }

  void writeAddrWindow(int16_t x, int16_t y, uint16_t w, uint16_t h) override {
    uint16_t x1 = x + w - 1, y1 = y + h - 1;
    if (_swap) {
      reg(0x21, x); reg(0x20, y);
      reg(0x52, x); reg(0x53, x1);
      reg(0x50, y); reg(0x51, y1);
    } else {
      reg(0x20, x); reg(0x21, y);
      reg(0x50, x); reg(0x51, x1);
      reg(0x52, y); reg(0x53, y1);
    }
    _bus->writeCommand16(0x22);  // write to GRAM
  }

  void invertDisplay(bool i) override {
    _bus->beginWrite();
    reg(0x61, i ? 0x0000 : 0x0001);  // this panel needs REV=1 for normal colours
    _bus->endWrite();
  }
  void displayOn() override { _bus->beginWrite(); reg(0x07, 0x0173); _bus->endWrite(); }
  void displayOff() override { _bus->beginWrite(); reg(0x07, 0x0000); _bus->endWrite(); }

protected:
  void tftInit() override {
    if (_rst != GFX_NOT_DEFINED) {
      pinMode(_rst, OUTPUT);
      digitalWrite(_rst, HIGH); delay(50);
      digitalWrite(_rst, LOW);  delay(50);
      digitalWrite(_rst, HIGH);
    }
    delay(100);
    static const uint16_t init[] = {
      0x0046, 0x0002, 0x0010, 0x1590, 0x0011, 0x0227, 0x0012, 0x80ff, 0x0013, 0x9c31,
      0xFFFF, 10,
      0x0002, 0x0300, 0x0003, 0x1030, 0x0060, 0xa700, 0x0061, 0x0001,
      0x0030, 0x0303, 0x0031, 0x0303, 0x0032, 0x0303, 0x0033, 0x0300, 0x0034, 0x0003,
      0x0035, 0x0303, 0x0036, 0x1400, 0x0037, 0x0303, 0x0038, 0x0303, 0x0039, 0x0303,
      0x003a, 0x0300, 0x003b, 0x0003, 0x003c, 0x0303, 0x003d, 0x1400,
      0x0020, 0x0000, 0x0021, 0x0000,
      0x0080, 0x0000, 0x0081, 0x0000, 0x0082, 0x0000, 0x0083, 0x0000, 0x0084, 0x0000, 0x0085, 0x0000,
      0x0092, 0x0200, 0x0093, 0x0303, 0x0090, 0x0010, 0x0000, 0x0001,
      0xFFFF, 200,
      0x0007, 0x0173,
    };
    for (size_t i = 0; i < sizeof(init) / sizeof(init[0]); i += 2) {
      if (init[i] == 0xFFFF) { delay(init[i + 1]); continue; }
      _bus->beginWrite();
      reg(init[i], init[i + 1]);
      _bus->endWrite();
    }
  }

private:
  bool _swap = false;
  void reg(uint16_t r, uint16_t v) { _bus->writeCommand16(r); _bus->write16(v); }
};
