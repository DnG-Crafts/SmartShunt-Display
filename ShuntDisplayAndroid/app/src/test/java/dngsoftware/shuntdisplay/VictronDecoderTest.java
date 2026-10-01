package dngsoftware.shuntdisplay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Test vectors from the victron-ble project (tests/test_battery_monitor.py). */
public class VictronDecoderTest {

    private static byte[] hex(String s) {
        byte[] b = new byte[s.length() / 2];
        for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
        return b;
    }

    @Test public void endToEnd() {
        byte[] data = hex("100289a302b040af925d09a4d89aa0128bdef48c6298a9");
        ShuntReading r = new ShuntReading();
        assertEquals(VictronDecoder.Result.OK,
                VictronDecoder.decode(data, VictronDecoder.parseKey("aff4d0995b7d1e176c0c33ecb9e70dcd"), r));
        assertEquals(12.53f, r.voltage, 0.001f);
        assertEquals(0f, r.current, 0.001f);
        assertEquals(50.0f, r.soc, 0.001f);
        assertEquals(-50.0f, r.consumedAh, 0.001f);
        assertEquals(-1, r.remainingMins);
        assertEquals(0, r.alarm);
        assertEquals(ShuntReading.AUX_NONE, r.auxMode);
        assertEquals("SmartShunt 500A/50mV", VictronDecoder.modelName(r.modelId));
    }

    @Test public void wrongKeyIsRejected() {
        byte[] data = hex("100289a302bb01af129087600b9b97bc2c32867c8238da");
        assertEquals(VictronDecoder.Result.BAD_KEY,
                VictronDecoder.decode(data, VictronDecoder.parseKey("ffffffffffffffffffffffffffffffff"), new ShuntReading()));
    }

    @Test public void auxStarter() {
        ShuntReading r = new ShuntReading();
        VictronDecoder.decodePlain(hex("ffffe6040000feff000000000080feac"), r);
        assertEquals(-0.02f, r.aux, 0.0001f);
    }

    @Test public void auxMidpoint() {
        ShuntReading r = new ShuntReading();
        VictronDecoder.decodePlain(hex("ffffe6040000feff010000000080fe0c"), r);
        assertEquals(655.34f, r.aux, 0.001f);
    }

    @Test public void auxTemperature() {
        ShuntReading r = new ShuntReading();
        VictronDecoder.decodePlain(hex("ffffe6040000ffff020000000080fede"), r);
        assertEquals(382.2f, r.aux, 0.01f);
    }

    @Test public void keyParsing() {
        assertNotNull(VictronDecoder.parseKey("AFF4D0995B7D1E176C0C33ECB9E70DCD"));
        assertNotNull(VictronDecoder.parseKey("aff4 d099 5b7d 1e17 6c0c 33ec b9e7 0dcd"));
        assertNull(VictronDecoder.parseKey("aff4d0"));
        assertNull(VictronDecoder.parseKey("zzf4d0995b7d1e176c0c33ecb9e70dcd"));
    }

    @Test public void alarmNames() {
        assertEquals("", VictronDecoder.alarmText(0));
        assertEquals("Low voltage", VictronDecoder.alarmText(1));
        assertTrue(VictronDecoder.alarmText(1 | 4).startsWith("Low voltage +1"));
    }

    // Captured charger packets from victron-ble (tests/test_ac_charger.py, test_solar_charger.py)
    @Test public void ip22EndToEnd() {
        ChargerReading r = new ChargerReading();
        assertEquals(VictronDecoder.Result.OK, VictronDecoder.decodeCharger(hex("100030a308f926c1b5170a0d2280335bf12d5ed083"),
                VictronDecoder.parseKey("c129cf8f75c3fe5a1655b481e205fb7d"), r));
        assertEquals(ChargerReading.KIND_MAINS, r.kind);
        assertEquals(6, r.state);                        // storage
        assertEquals(0, r.error);
        assertEquals(13.49f, r.voltage, 0.001f);
        assertEquals(0.4f, r.current, 0.001f);
        assertEquals(13.49f * 0.4f, r.power, 0.01f);
        assertEquals(0xA330, r.modelId);
    }

    @Test public void mpptEndToEnd() {
        ChargerReading r = new ChargerReading();
        assertEquals(VictronDecoder.Result.OK, VictronDecoder.decodeCharger(hex("100242a0016207adceb37b605d7e0ee21b24df5c"),
                VictronDecoder.parseKey("adeccb947395801a4dd45a2eaa44bf17"), r));
        assertEquals(ChargerReading.KIND_SOLAR, r.kind);
        assertEquals(4, r.state);                        // absorption
        assertEquals(13.88f, r.voltage, 0.001f);
        assertEquals(1.4f, r.current, 0.001f);
        VictronDecoder.decodeChargerPlain(VictronDecoder.REC_SOLAR, hex("0300fb09650032000901ffff31bc45ad"), r);
        assertEquals(25.55f, r.voltage, 0.001f);
        assertEquals(10.1f, r.current, 0.001f);
    }

    @Test public void orionXs() {
        // state 3 (bulk), no error, 13.60 V and 20.5 A out
        byte[] plain = hex("03005005cd0000000000000000000000");
        ChargerReading r = new ChargerReading();
        VictronDecoder.decodeChargerPlain(VictronDecoder.REC_ORION_XS, plain, r);
        assertEquals(ChargerReading.KIND_DCDC, r.kind);
        assertEquals(3, r.state);
        assertEquals(13.6f * 20.5f, r.power, 0.01f);
    }

    @Test public void chargerIsNotAShunt() {
        byte[] ip22 = hex("100030a308f926c1b5170a0d2280335bf12d5ed083");
        assertEquals(VictronDecoder.Result.NOT_BATTERY_MONITOR,
                VictronDecoder.decode(ip22, VictronDecoder.parseKey("c129cf8f75c3fe5a1655b481e205fb7d"), new ShuntReading()));
        assertEquals(VictronDecoder.Result.BAD_KEY,
                VictronDecoder.decodeCharger(ip22, VictronDecoder.parseKey("ffffffffffffffffffffffffffffffff"), new ChargerReading()));
        assertEquals(VictronDecoder.Result.NOT_CHARGER, VictronDecoder.decodeCharger(hex("100289a302b040af925d09a4d89aa0128bdef48c6298a9"),
                VictronDecoder.parseKey("aff4d0995b7d1e176c0c33ecb9e70dcd"), new ChargerReading()));
    }
}
