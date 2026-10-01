package dngsoftware.shuntdisplay;

import java.security.GeneralSecurityException;
import java.util.Locale;

import javax.crypto.Cipher;
import javax.crypto.spec.SecretKeySpec;

/**
 * Decodes Victron "Instant Readout" Bluetooth advertisements from battery monitors
 * (SmartShunt, BMV-71x) and chargers (Blue Smart IP22, SmartSolar MPPT, Orion XS).
 * Same format and rules as victron.h in the Arduino version.
 *
 * Manufacturer data (company ID 0x02E1, already stripped by Android):
 *   [0..1] record prefix   [2..3] model ID (LE)   [4] record type (0x02 = battery monitor)
 *   [5..6] IV / counter (LE)   [7] first byte of the key   [8..] AES-128-CTR payload
 */
public final class VictronDecoder {

    public static final int VICTRON_COMPANY_ID = 0x02E1;

    public enum Result { OK, NOT_VICTRON, NOT_BATTERY_MONITOR, NOT_CHARGER, BAD_KEY }

    /** Record types (byte 4). */
    public static final int REC_SOLAR = 0x01, REC_BATTERY = 0x02, REC_AC_CHARGER = 0x08, REC_ORION_XS = 0x0F;

    private VictronDecoder() {}

    /** Parses a 32-hex-digit key (spaces, dashes and colons allowed). Returns null if invalid. */
    public static byte[] parseKey(String hex) {
        String h = Settings.hexOnly(hex, 32);
        if (h == null) return null;
        byte[] key = new byte[16];
        for (int i = 0; i < 16; i++) key[i] = (byte) Integer.parseInt(h.substring(i * 2, i * 2 + 2), 16);
        return key;
    }

    /** Model ID from an advertisement, or 0. */
    public static int modelId(byte[] d) {
        return d != null && d.length >= 4 ? (d[2] & 0xFF) | ((d[3] & 0xFF) << 8) : 0;
    }

    /** True if this advertisement is a battery-monitor record. */
    public static boolean isBatteryMonitor(byte[] d) {
        return d != null && d.length >= 9 && (d[0] & 0xFF) == 0x10 && (d[4] & 0xFF) == 0x02;
    }

    /** Record type of a Victron advertisement, or -1. */
    public static int recordType(byte[] d) {
        return d != null && d.length >= 9 && (d[0] & 0xFF) == 0x10 ? d[4] & 0xFF : -1;
    }

    /** The charger kind (ChargerReading.KIND_*) for a record type, or -1 if it isn't a charger. */
    public static int chargerKind(int recordType) {
        switch (recordType) {
            case REC_AC_CHARGER: return ChargerReading.KIND_MAINS;
            case REC_SOLAR: return ChargerReading.KIND_SOLAR;
            case REC_ORION_XS: return ChargerReading.KIND_DCDC;
            default: return -1;
        }
    }

    /** Decodes {@code d} (manufacturer data without company ID) into {@code out}. */
    public static Result decode(byte[] d, byte[] key, ShuntReading out) {
        if (d == null || d.length < 9 || (d[0] & 0xFF) != 0x10) return Result.NOT_VICTRON;
        if ((d[4] & 0xFF) != REC_BATTERY) return Result.NOT_BATTERY_MONITOR;
        byte[] plain = decrypt(d, key);
        if (plain == null) return Result.BAD_KEY;
        decodePlain(plain, out);
        out.modelId = modelId(d);
        return Result.OK;
    }

    /** Decodes a charger's advertisement into {@code out}. */
    public static Result decodeCharger(byte[] d, byte[] key, ChargerReading out) {
        if (d == null || d.length < 9 || (d[0] & 0xFF) != 0x10) return Result.NOT_VICTRON;
        if (chargerKind(d[4] & 0xFF) < 0) return Result.NOT_CHARGER;
        byte[] plain = decrypt(d, key);
        if (plain == null) return Result.BAD_KEY;
        decodeChargerPlain(d[4] & 0xFF, plain, out);
        out.modelId = modelId(d);
        return Result.OK;
    }

    /**
     * Charger record layouts from Victron's "extra manufacturer data" document (Orion XS: as
     * decoded by the victron-ble and esphome-victron_ble projects).
     */
    public static void decodeChargerPlain(int rec, byte[] plain, ChargerReading out) {
        BitReader r = new BitReader(plain);
        out.kind = chargerKind(rec);
        int state = r.bits(8), error = r.bits(8);
        out.state = state == 0xFF ? -1 : state;
        out.error = error == 0xFF ? -1 : error;
        out.voltage = out.current = out.power = Float.NaN;
        if (rec == REC_AC_CHARGER) {
            // up to three outputs: 13-bit volts (0.01 V) and 11-bit amps (0.1 A) each
            float watts = 0, amps = 0;
            boolean any = false;
            for (int i = 0; i < 3; i++) {
                int v = r.bits(13), a = r.bits(11);
                if (v == 0x1FFF || a == 0x7FF) continue;
                if (i == 0) out.voltage = v / 100f;
                watts += v / 100f * (a / 10f);
                amps += a / 10f;
                any = true;
            }
            if (any) { out.current = amps; out.power = watts; }
        } else if (rec == REC_SOLAR) {
            int v = r.bits(16), a = r.bits(16);
            r.bits(16);                                  // yield today
            int pv = r.bits(16);
            out.voltage = v == 0x7FFF ? Float.NaN : BitReader.signed(v, 16) / 100f;
            out.current = a == 0x7FFF ? Float.NaN : BitReader.signed(a, 16) / 10f;
            if (!Float.isNaN(out.voltage) && !Float.isNaN(out.current)) out.power = out.voltage * out.current;
            else if (pv != 0xFFFF) out.power = pv;
        } else if (rec == REC_ORION_XS) {
            int v = r.bits(16), a = r.bits(16);
            out.voltage = v == 0xFFFF ? Float.NaN : v / 100f;
            out.current = a == 0xFFFF ? Float.NaN : a / 10f;
            if (!Float.isNaN(out.voltage) && !Float.isNaN(out.current)) out.power = out.voltage * out.current;
        }
    }

    /** The AES-128-CTR payload, or null if the key's first byte doesn't match. */
    private static byte[] decrypt(byte[] d, byte[] key) {
        if (key == null || key.length != 16 || d[7] != key[0]) return null;
        int iv = (d[5] & 0xFF) | ((d[6] & 0xFF) << 8);
        int n = Math.min(d.length - 8, 32);
        byte[] plain = new byte[32];
        try {
            // AES-CTR with a 128-bit *little-endian* counter (Java's CTR mode counts big-endian,
            // so the counter blocks are built by hand and encrypted with ECB).
            Cipher aes = Cipher.getInstance("AES/ECB/NoPadding");
            aes.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"));
            for (int off = 0; off < n; off += 16) {
                long ctr = iv + off / 16;
                byte[] block = new byte[16];
                block[0] = (byte) ctr; block[1] = (byte) (ctr >> 8); block[2] = (byte) (ctr >> 16);
                byte[] ks = aes.doFinal(block);
                for (int i = 0; i < 16 && off + i < n; i++) plain[off + i] = (byte) (d[8 + off + i] ^ ks[i]);
            }
        } catch (GeneralSecurityException e) {
            return null;
        }
        return plain;
    }

    /** Decodes an already-decrypted battery-monitor payload (at least 15 bytes). */
    public static void decodePlain(byte[] plain, ShuntReading out) {
        BitReader r = new BitReader(plain);
        int remaining = r.bits(16);
        int voltage = BitReader.signed(r.bits(16), 16);
        int alarm = r.bits(16);
        int aux = r.bits(16);
        int auxMode = r.bits(2);
        int current = r.bits(22);
        int consumed = r.bits(20);
        int soc = r.bits(10);

        out.remainingMins = remaining == 0xFFFF ? -1 : remaining;
        out.voltage = voltage == 0x7FFF ? Float.NaN : voltage / 100f;
        out.alarm = alarm;
        out.auxMode = auxMode;
        out.current = current == 0x3FFFFF ? Float.NaN : BitReader.signed(current, 22) / 1000f;
        out.consumedAh = consumed == 0xFFFFF ? Float.NaN : -consumed / 10f;
        out.soc = soc == 0x3FF ? Float.NaN : soc / 10f;
        out.aux = Float.NaN;
        if (auxMode == ShuntReading.AUX_STARTER) out.aux = BitReader.signed(aux, 16) / 100f;
        else if (auxMode == ShuntReading.AUX_MIDPOINT) out.aux = aux / 100f;
        else if (auxMode == ShuntReading.AUX_TEMPERATURE) out.aux = aux / 100f - 273.15f;
    }

    /** Reads bit fields least-significant bit first. */
    static final class BitReader {
        private final byte[] buf;
        private int pos;
        BitReader(byte[] buf) { this.buf = buf; }
        int bits(int count) {
            int v = 0;
            for (int i = 0; i < count; i++, pos++) v |= ((buf[pos >> 3] >> (pos & 7)) & 1) << i;
            return v;
        }
        static int signed(int v, int bits) {
            return (v & (1 << (bits - 1))) != 0 ? v - (1 << bits) : v;
        }
    }

    // ------------------------------------------------------------ names

    private static final String[] ALARMS = {
            "Low voltage", "High voltage", "Low SOC", "Low starter voltage", "High starter voltage",
            "Low temperature", "High temperature", "Midpoint voltage", "Overload", "DC ripple",
            "Low AC out voltage", "High AC out voltage", "Short circuit", "BMS lockout"};

    /** Human-readable alarm, e.g. "Low voltage" (or "Low voltage +1" if several are active). */
    public static String alarmText(int alarm) {
        if (alarm == 0) return "";
        String first = null;
        int count = 0;
        for (int i = 0; i < ALARMS.length; i++) {
            if ((alarm & (1 << i)) != 0) { if (first == null) first = ALARMS[i]; count++; }
        }
        if (first == null) return String.format(Locale.US, "Alarm 0x%04X", alarm);
        return count > 1 ? first + " +" + (count - 1) : first;
    }

    /** Model name for battery monitors (from the victron-ble model table), or null. */
    public static String modelName(int id) {
        switch (id) {
            case 0xA380: return "BMV-710 Smart";
            case 0xA381: case 0xA383: return "BMV-712 Smart";
            case 0xA382: return "BMV-710H Smart";
            case 0xA389: return "SmartShunt 500A/50mV";
            case 0xA38A: return "SmartShunt 1000A/50mV";
            case 0xA38B: return "SmartShunt 2000A/50mV";
            case 0xA38C: return "SmartShunt IP67 500A/50mV";
            case 0xA38D: return "SmartShunt IP67 1000A/50mV";
            case 0xA38E: return "SmartShunt IP67 2000A/50mV";
            case 0xC030: case 0xC035: return "SmartShunt IP65 500A/50mV";
            case 0xC031: case 0xC036: return "SmartShunt IP65 1000A/50mV";
            case 0xC032: case 0xC037: return "SmartShunt IP65 2000A/50mV";
            case 0xC038: return "SmartShunt 300A/50mV";
            default: return null;
        }
    }
}
