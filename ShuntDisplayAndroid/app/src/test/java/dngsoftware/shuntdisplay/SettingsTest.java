package dngsoftware.shuntdisplay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class SettingsTest {

    @Test public void macFormats() {
        assertEquals("c0:3b:12:34:56:78", Settings.normaliseMac("c03b12345678"));
        assertEquals("c0:3b:12:34:56:78", Settings.normaliseMac("C0:3B:12:34:56:78"));
        assertEquals("c0:3b:12:34:56:78", Settings.normaliseMac("c0-3b-12-34-56-78"));
        assertNull(Settings.normaliseMac("c03b1234567"));
        assertNull(Settings.normaliseMac("c03b1234567g"));
    }

    @Test public void importArduinoFile() {
        String file = "# comment\r\n"
                + "mac = C03B12345678\r\n"
                + "key = AFF4D0995B7D1E176C0C33ECB9E70DCD\r\n"
                + "demo = 1\r\n"
                + "rotation = 3\r\n"
                + "lcd_chip = 9341\r\n"
                + "invert = 0\r\n"
                + "stale_after = 45\r\n"
                + "soc_amber = 40\r\n"
                + "soc_red = 15\r\n"
                + "screen_off = 120\r\n"
                + "touch_cal = 1, 1, 912, 105, 130, 880, 9341\r\n";
        Settings.ImportResult r = new Settings().importConfig(file);
        Settings s = r.settings;
        assertEquals(0, r.badLines);
        assertEquals("c0:3b:12:34:56:78", s.mac);
        assertEquals("aff4d0995b7d1e176c0c33ecb9e70dcd", s.key);
        assertTrue(s.demo);
        assertEquals(45, s.staleAfterS);
        assertEquals(40, s.socAmber);
        assertEquals(15, s.socRed);
        assertEquals(120, s.screenOffS);
        assertFalse(s.needsSetup());
        // Arduino-only lines survive an export
        String out = s.exportConfig();
        assertTrue(out.contains("rotation = 3"));
        assertTrue(out.contains("touch_cal = 1, 1, 912, 105, 130, 880, 9341"));
        // and the export reads back identically
        Settings.ImportResult again = new Settings().importConfig(out);
        assertEquals(0, again.badLines);
        assertEquals(s.mac, again.settings.mac);
        assertEquals(s.key, again.settings.key);
        assertEquals(s.screenOffS, again.settings.screenOffS);
    }

    @Test public void badLinesAreCounted() {
        Settings.ImportResult r = new Settings().importConfig("colour = blue\nkey = tooshort\nrotation = 1\n");
        assertEquals(2, r.badLines);
    }

    @Test public void chargerSettingsRoundTrip() {
        Settings.ImportResult r = new Settings().importConfig("charger1_mac = C0:FF:EE:00:00:01\ncharger1_key = "
                + "abababababababababababababababab\nother_source = DCDC\ncharger2_mac = nonsense\ncharger3_mac = c0:ff:ee:00:00:03\n");
        assertEquals(2, r.badLines);
        assertEquals("c0:ff:ee:00:00:01", r.settings.chargerMac[0]);
        assertEquals(1, r.settings.chargerCount());
        assertEquals("dcdc", r.settings.otherSource);
        Settings.ImportResult again = new Settings().importConfig(r.settings.exportConfig());
        assertEquals(0, again.badLines);
        assertEquals(r.settings.exportConfig(), again.settings.exportConfig());
    }

    @Test public void halfFilledChargerIsNotUsed() {
        Settings s = new Settings().importConfig("charger2_mac = c0:ff:ee:00:00:02\n").settings;
        assertEquals(0, s.chargerCount());
    }

    @Test public void loadsIcon() {
        Settings.ImportResult r = new Settings().importConfig("loads_icon = Boat\nloads_icon = tent\n");
        assertEquals("boat", r.settings.loadsIcon);
        assertEquals(1, r.badLines);
        assertTrue(r.settings.exportConfig().contains("loads_icon = boat"));
    }
}
