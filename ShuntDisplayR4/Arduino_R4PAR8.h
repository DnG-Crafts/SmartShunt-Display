// 8-bit parallel bus for MCUFriend-style shields on the Arduino UNO R4 (WiFi & Minima),
// with a longer write strobe than Arduino_UNOPAR8 so slower controllers such as the
// UC8230 on the Jaycar XC4630 latch every byte.
// Pins: D8,D9,D2..D7 = LCD D0..D7, A0 = RD, A1 = WR, A2 = RS (DC), A3 = CS, A4 = RESET.
#pragma once
#include <Arduino_GFX_Library.h>

#ifndef R4BUS_WR_HOLD
#define R4BUS_WR_HOLD 4   // extra register writes while WR is low (~40 ns each)
#endif

class Arduino_R4PAR8 : public Arduino_DataBus {
public:
  bool begin(int32_t = GFX_NOT_DEFINED, int8_t = GFX_NOT_DEFINED) override {
    pinMode(A0, OUTPUT); digitalWrite(A0, HIGH);  // RD idle
    pinMode(A1, OUTPUT); digitalWrite(A1, HIGH);  // WR idle
    pinMode(A2, OUTPUT); digitalWrite(A2, HIGH);  // RS = data
    pinMode(A3, OUTPUT); digitalWrite(A3, HIGH);  // CS idle
    for (int p = 2; p <= 9; p++) pinMode(p, OUTPUT);
    return true;
  }
  void beginWrite() override { dcHigh(); csLow(); }
  void endWrite() override { csHigh(); }
  void writeCommand(uint8_t c) override { dcLow(); wr(c); dcHigh(); }
  void writeCommand16(uint16_t c) override { dcLow(); wr(c >> 8); wr(c); dcHigh(); }
  void writeCommandBytes(uint8_t *d, uint32_t n) override { dcLow(); while (n--) wr(*d++); dcHigh(); }
  void write(uint8_t d) override { wr(d); }
  void write16(uint16_t d) override { wr(d >> 8); wr(d); }
  void writeRepeat(uint16_t p, uint32_t n) override { while (n--) { wr(p >> 8); wr(p); } }
  void writeBytes(uint8_t *d, uint32_t n) override { while (n--) wr(*d++); }
  void writePixels(uint16_t *d, uint32_t n) override { while (n--) { uint16_t p = *d++; wr(p >> 8); wr(p); } }

private:
  static inline void dcHigh() { R_PORT0->POSR = bit(1); }
  static inline void dcLow()  { R_PORT0->PORR = bit(1); }
  static inline void csHigh() { R_PORT0->POSR = bit(2); }
  static inline void csLow()  { R_PORT0->PORR = bit(2); }

  static inline void wr(uint8_t d) {
    // D0 -> D8, D1 -> D9
#if defined(ARDUINO_UNOR4_WIFI)
    R_PORT3->PORR = 0x18;
    R_PORT3->POSR = ((d & 0x01) << 4) | ((d & 0x02) << 2);   // D8=P304, D9=P303
    R_PORT1->PORR = 0x18F0;
    R_PORT1->POSR = ((d & 0x3C) << 2) | ((d & 0xC0) << 5);   // D2-D5=P104-P107, D6-D7=P111-P112
#else // other boards: slower generic path
    static const uint8_t pins[8] = {8, 9, 2, 3, 4, 5, 6, 7};
    for (int i = 0; i < 8; i++) digitalWrite(pins[i], (d >> i) & 1);
#endif
    R_PORT0->PORR = bit(0);                 // WR low (A1 = P000)
    for (int i = 0; i < R4BUS_WR_HOLD; i++) R_PORT0->PORR = bit(0);  // hold it low a little
    R_PORT0->POSR = bit(0);                 // WR high: byte latched
    R_PORT0->POSR = bit(0);
  }
};
