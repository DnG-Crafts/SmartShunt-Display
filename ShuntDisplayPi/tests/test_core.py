"""Unit tests (no screen or Bluetooth needed): python3 -m unittest discover tests"""
import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shuntdisplay import config, i18n, victron  # noqa: E402


class Decoder(unittest.TestCase):
    # Test vectors from the victron-ble project (tests/test_battery_monitor.py)
    def test_aes_fips197(self):
        rk = victron._expand_key(bytes.fromhex("000102030405060708090a0b0c0d0e0f"))
        self.assertEqual(victron.aes128_encrypt_block(rk, bytes.fromhex("00112233445566778899aabbccddeeff")).hex(),
                         "69c4e0d86a7b0430d8cdb78070b4c55a")

    def test_end_to_end(self):
        res, r = victron.decode(bytes.fromhex("100289a302b040af925d09a4d89aa0128bdef48c6298a9"),
                                victron.parse_key("aff4d0995b7d1e176c0c33ecb9e70dcd"))
        self.assertEqual(res, victron.OK)
        self.assertAlmostEqual(r.voltage, 12.53)
        self.assertAlmostEqual(r.current, 0)
        self.assertAlmostEqual(r.soc, 50.0)
        self.assertAlmostEqual(r.consumed_ah, -50.0)
        self.assertEqual(r.remaining_mins, -1)
        self.assertEqual(r.alarm, 0)
        self.assertEqual(r.aux_mode, victron.AUX_NONE)
        self.assertEqual(victron.model_name(r.model_id), "SmartShunt 500A/50mV")

    def test_wrong_key(self):
        res, _ = victron.decode(bytes.fromhex("100289a302bb01af129087600b9b97bc2c32867c8238da"),
                                victron.parse_key("ffffffffffffffffffffffffffffffff"))
        self.assertEqual(res, victron.BAD_KEY)

    # Captured packets from the victron-ble project's tests
    def test_ip22_end_to_end(self):
        res, r = victron.decode_charger(bytes.fromhex("100030a308f926c1b5170a0d2280335bf12d5ed083"),
                                        victron.parse_key("c129cf8f75c3fe5a1655b481e205fb7d"))
        self.assertEqual(res, victron.OK)
        self.assertEqual(r.kind, "mains")
        self.assertEqual(r.state, 6)                  # storage
        self.assertEqual(r.error, 0)
        self.assertAlmostEqual(r.voltage, 13.49)
        self.assertAlmostEqual(r.current, 0.4)
        self.assertAlmostEqual(r.power, 13.49 * 0.4)
        self.assertEqual(r.model_id, 0xA330)

    def test_mppt_end_to_end(self):
        res, r = victron.decode_charger(bytes.fromhex("100242a0016207adceb37b605d7e0ee21b24df5c"),
                                        victron.parse_key("adeccb947395801a4dd45a2eaa44bf17"))
        self.assertEqual(res, victron.OK)
        self.assertEqual((r.kind, r.state), ("solar", 4))
        self.assertAlmostEqual(r.voltage, 13.88)
        self.assertAlmostEqual(r.current, 1.4)
        r = victron.decode_charger_plain(0x01, bytes.fromhex("0300fb09650032000901ffff31bc45ad"))
        self.assertAlmostEqual(r.voltage, 25.55)
        self.assertAlmostEqual(r.current, 10.1)

    def test_orion_xs(self):
        # state 3 (bulk), no error, 13.60 V out, 20.5 A out
        plain = bytes([3, 0]) + (1360).to_bytes(2, "little") + (205).to_bytes(2, "little") + bytes(10)
        r = victron.decode_charger_plain(0x0F, plain)
        self.assertEqual((r.kind, r.state), ("dcdc", 3))
        self.assertAlmostEqual(r.power, 13.6 * 20.5)

    def test_charger_is_not_a_shunt(self):
        d = bytes.fromhex("100030a308f926c1b5170a0d2280335bf12d5ed083")
        self.assertEqual(victron.decode(d, victron.parse_key("c129cf8f75c3fe5a1655b481e205fb7d"))[0],
                         victron.NOT_BATTERY_MONITOR)
        self.assertTrue(victron.is_charger(d))
        self.assertEqual(victron.decode_charger(d, victron.parse_key("ff" * 16))[0], victron.BAD_KEY)
        shunt = bytes.fromhex("100289a302b040af925d09a4d89aa0128bdef48c6298a9")
        self.assertEqual(victron.decode_charger(shunt, victron.parse_key("aff4d0995b7d1e176c0c33ecb9e70dcd"))[0],
                         victron.NOT_CHARGER)

    def test_aux(self):
        self.assertAlmostEqual(victron.decode_plain(bytes.fromhex("ffffe6040000feff000000000080feac")).aux, -0.02)
        self.assertAlmostEqual(victron.decode_plain(bytes.fromhex("ffffe6040000feff010000000080fe0c")).aux, 655.34)
        self.assertAlmostEqual(victron.decode_plain(bytes.fromhex("ffffe6040000ffff020000000080fede")).aux, 382.2, 1)

    def test_key_and_mac_parsing(self):
        self.assertIsNotNone(victron.parse_key("AFF4D0995B7D1E176C0C33ECB9E70DCD"))
        self.assertIsNotNone(victron.parse_key("aff4 d099 5b7d 1e17 6c0c 33ec b9e7 0dcd"))
        self.assertIsNone(victron.parse_key("aff4d0"))
        self.assertIsNone(victron.parse_key("zzf4d0995b7d1e176c0c33ecb9e70dcd"))
        self.assertEqual(victron.normalise_mac("C03B12345678"), "c0:3b:12:34:56:78")
        self.assertEqual(victron.normalise_mac("c0-3b-12-34-56-78"), "c0:3b:12:34:56:78")
        self.assertIsNone(victron.normalise_mac("c03b1234567"))


class Config(unittest.TestCase):
    ARDUINO = """# SmartShunt display settings
mac = C0:3B:12:34:56:78
key = aff4d0995b7d1e176c0c33ecb9e70dcd
demo = 0
rotation = 1
lcd_chip = 9341
invert = 0
stale_after = 45
soc_amber = 60
soc_red = 25
screen_off = 30
touch_cal = 1 1 0 100 900 120 880
bogus line
colour = blue
"""

    def test_arduino_file(self):
        s, bad = config.Settings().import_text(self.ARDUINO)
        self.assertEqual(bad, 2)
        self.assertEqual(s.mac, "c0:3b:12:34:56:78")
        self.assertEqual((s.stale_after, s.soc_amber, s.soc_red, s.screen_off), (45, 60, 25, 30))
        self.assertEqual(len(s.passthrough), 4)          # rotation, lcd_chip, invert, touch_cal kept

    def test_round_trip(self):
        s, _ = config.Settings().import_text(self.ARDUINO)
        s.language, s.theme, s.screen_rotation, s.brightness = "zh-TW", config.THEME_LIGHT, 270, 40
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "CONFIG.TXT")
            config.save(s, p)
            t, bad, existed = config.load(p)
        self.assertTrue(existed)
        self.assertEqual(bad, 0)
        self.assertEqual(t, s)

    def test_needs_setup(self):
        self.assertTrue(config.Settings().needs_setup())
        s, _ = config.Settings().import_text(self.ARDUINO)
        self.assertFalse(s.needs_setup())


class Translations(unittest.TestCase):
    def test_every_language_complete(self):
        folder = os.path.join(os.path.dirname(i18n.__file__), "lang")
        with open(os.path.join(folder, "en.json"), encoding="utf-8") as f:
            en = json.load(f)
        tags, names = i18n.available()
        self.assertEqual(len(tags), 45)
        for tag in tags:
            s = i18n.Strings(tag)
            self.assertEqual(s.tag, tag)
            for k, v in en.items():
                if isinstance(v, str) and "%" in v:
                    got = s._d[k]
                    self.assertEqual(sorted(i18n._FMT.findall(v)), sorted(i18n._FMT.findall(got)), (tag, k))
            self.assertEqual(len(s.array("alarm_names")), 14, tag)
            self.assertTrue(s.plural("scanning_others", 3))

    def test_format(self):
        self.assertEqual(i18n.fmt("%1$dh %2$02dm", 3, 7), "3h 07m")
        self.assertEqual(i18n.fmt("%2$s-%1$s", "a", "b"), "b-a")
        self.assertEqual(i18n.fmt("%1$d%%", 50), "50%")

    def test_plurals(self):
        self.assertEqual([i18n.plural_category("ru", n) for n in (1, 2, 5, 11, 21, 22)],
                         ["one", "few", "many", "many", "one", "few"])
        self.assertEqual(i18n.plural_category("ja", 1), "other")
        self.assertEqual(i18n.plural_category("fr", 0), "one")
        self.assertEqual([i18n.plural_category("sl", n) for n in (1, 2, 3, 5, 101)], ["one", "two", "few", "other", "one"])

    def test_system_language(self):
        self.assertEqual(i18n.match_tag("de_DE.UTF-8"), "de")
        self.assertEqual(i18n.match_tag("zh_TW.UTF-8"), "zh-TW")
        self.assertEqual(i18n.match_tag("zh_HK"), "zh-TW")
        self.assertEqual(i18n.match_tag("zh_CN.UTF-8"), "zh-CN")
        self.assertEqual(i18n.match_tag("nb_NO.UTF-8"), "nb")
        self.assertEqual(i18n.match_tag("id_ID"), "id")
        self.assertIsNone(i18n.match_tag("C.UTF-8"))
        self.assertIsNone(i18n.match_tag("xx_YY"))

    def test_decimal_comma(self):
        self.assertTrue(i18n.Strings("de").decimal_comma)
        self.assertFalse(i18n.Strings("ja").decimal_comma)


if __name__ == "__main__":
    unittest.main()


class Flow(unittest.TestCase):
    """The flow picture's sums: flow_nodes() with and without extra chargers."""

    def nodes(self, pw, chargers=(), other="auto"):
        from shuntdisplay.dashboard import flow_nodes
        s = config.Settings()
        s.other_source = other
        t = i18n.Strings("en")
        return {n.place: n for n in flow_nodes(t, pw, s, list(chargers))}

    def charger(self, watts, kind="mains", state=5):
        r = victron.ChargerReading(kind)
        r.power, r.state, r.error = watts, state, 0
        return r

    def test_no_chargers(self):
        n = self.nodes(200.0)
        self.assertEqual((n["top"].flow, n["right"].flow, n["top"].label), (200.0, 0.0, "Charger"))
        n = self.nodes(-150.0)
        self.assertEqual((n["top"].flow, n["right"].flow), (0.0, 150.0 * -1))
        self.assertNotIn("left", n)

    def test_mains_charger_runs_the_loads(self):
        n = self.nodes(192.0, [(0, self.charger(312.0), "")])
        self.assertEqual(n["left"].flow, 312.0)
        self.assertEqual(n["left"].label, "Mains")
        self.assertEqual(n["left"].extra, "Float")
        self.assertAlmostEqual(-n["right"].flow, 120.0)       # loads
        self.assertEqual(n["top"].flow, 0.0)                   # nothing else charging
        self.assertEqual(n["top"].label, "Other")

    def test_unknown_charger_shows_as_other(self):
        n = self.nodes(450.0, [(0, self.charger(312.0, state=3), "")], other="dcdc")
        self.assertAlmostEqual(n["top"].flow, 138.0)
        self.assertEqual((n["top"].label, n["top"].icon), ("DC-DC", "car"))
        self.assertEqual(n["right"].flow, 0.0)

    def test_charger_off_battery_runs_the_loads(self):
        n = self.nodes(-276.0, [(0, self.charger(0.0, state=0), "")])
        self.assertAlmostEqual(-n["right"].flow, 276.0)
        self.assertEqual(n["left"].extra, "Off")

    def test_stale_charger(self):
        n = self.nodes(-100.0, [(0, None, "no_signal")])
        self.assertEqual(n["left"].value, "--")
        self.assertEqual(n["left"].extra, "No signal")
        self.assertAlmostEqual(-n["right"].flow, 100.0)

    def test_two_chargers(self):
        n = self.nodes(-79.0, [(0, self.charger(0.0, state=0), ""), (1, self.charger(148.0, "solar", 3), "")])
        self.assertEqual((n["left"].label, n["top"].label, n["top"].icon), ("Mains", "Solar", "solar"))
        self.assertAlmostEqual(-n["right"].flow, 227.0)
        self.assertEqual(len(n), 3)                            # no "other" node: no room


class ChargerSettings(unittest.TestCase):
    def test_round_trip(self):
        s, bad = config.Settings().import_text(
            "charger1_mac = C0:FF:EE:00:00:01\ncharger1_key = " + "ab" * 16 + "\nother_source = DCDC\n"
            "charger2_mac = nonsense\ncharger3_mac = c0:ff:ee:00:00:03\n")
        self.assertEqual(bad, 2)
        self.assertEqual(s.chargers(), [(0, "c0:ff:ee:00:00:01", "ab" * 16)])
        self.assertEqual(s.other_source, "dcdc")
        s2, bad2 = config.Settings().import_text(s.export_text())
        self.assertEqual((bad2, s2), (0, s))

    def test_loads_icon(self):
        s, bad = config.Settings().import_text("loads_icon = Caravan\nloads_icon = tent\n")
        self.assertEqual((s.loads_icon, bad), ("caravan", 1))
        self.assertIn("loads_icon = caravan", s.export_text())

    def test_half_filled_slot_is_not_used(self):
        s, _ = config.Settings().import_text("charger2_mac = c0:ff:ee:00:00:02\n")
        self.assertEqual(s.chargers(), [])
