package dngsoftware.shuntdisplay;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.Locale;

/**
 * All app settings. Stored in SharedPreferences, and can be exported/imported as a CONFIG.TXT
 * in the same format the Arduino display reads from its SD card.
 */
public final class Settings {

    public static final int THEME_SYSTEM = 0, THEME_LIGHT = 1, THEME_DARK = 2;
    public static final int ORIENT_AUTO = 0, ORIENT_PORTRAIT = 1, ORIENT_LANDSCAPE = 2, ORIENT_LANDSCAPE_FLIPPED = 3;

    // Shared with the Arduino display (and CONFIG.TXT)
    public String mac = "";               // "aa:bb:cc:dd:ee:ff" or empty
    public String key = "";               // 32 lower-case hex digits or empty
    public boolean demo = false;
    public int staleAfterS = 30;
    public int socAmber = 50;
    public int socRed = 20;
    public int screenOffS = 30;           // the Arduino display's screen timeout; not used by the app

    /** Extra Victron chargers (Blue Smart IP22, SmartSolar MPPT, Orion XS): MAC and key per slot. */
    public static final int CHARGER_SLOTS = 2;
    public String[] chargerMac = {"", ""};
    public String[] chargerKey = {"", ""};
    /** What to call charging the extra chargers don't account for. */
    public static final String[] OTHER_SOURCES = {"auto", "dcdc", "solar", "mains", "alternator"};
    public String otherSource = "auto";
    /** The picture on the Loads node. */
    public static final String[] LOADS_ICONS = {"house", "caravan", "boat"};
    public String loadsIcon = "house";

    // Phone only
    public int theme = THEME_SYSTEM;
    public int orientation = ORIENT_AUTO;
    public boolean keepAwake = false;
    public boolean fullScreen = true;    // hide the status and navigation bars on the dashboard

    /** CONFIG.TXT lines for the Arduino only (rotation, lcd_chip, invert, touch_cal), kept for export. */
    public String passthrough = "";

    private static final String PREFS = "settings";

    // ------------------------------------------------------------ storage

    public static Settings load(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        Settings s = new Settings();
        s.mac = p.getString("mac", s.mac);
        s.key = p.getString("key", s.key);
        s.demo = p.getBoolean("demo", s.demo);
        s.staleAfterS = p.getInt("stale_after", s.staleAfterS);
        s.socAmber = p.getInt("soc_amber", s.socAmber);
        s.socRed = p.getInt("soc_red", s.socRed);
        s.screenOffS = p.getInt("screen_off", s.screenOffS);
        s.theme = p.getInt("theme", s.theme);
        s.orientation = p.getInt("orientation", s.orientation);
        s.keepAwake = p.getBoolean("keep_awake", s.keepAwake);
        s.fullScreen = p.getBoolean("full_screen", s.fullScreen);
        s.passthrough = p.getString("passthrough", s.passthrough);
        for (int i = 0; i < CHARGER_SLOTS; i++) {
            s.chargerMac[i] = p.getString("charger" + (i + 1) + "_mac", "");
            s.chargerKey[i] = p.getString("charger" + (i + 1) + "_key", "");
        }
        s.otherSource = p.getString("other_source", s.otherSource);
        s.loadsIcon = p.getString("loads_icon", s.loadsIcon);
        return s;
    }

    public void save(Context ctx) {
        SharedPreferences.Editor e = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit();
        for (int i = 0; i < CHARGER_SLOTS; i++) {
            e.putString("charger" + (i + 1) + "_mac", chargerMac[i]).putString("charger" + (i + 1) + "_key", chargerKey[i]);
        }
        e.putString("other_source", otherSource).putString("loads_icon", loadsIcon)
                .putString("mac", mac).putString("key", key).putBoolean("demo", demo)
                .putInt("stale_after", staleAfterS).putInt("soc_amber", socAmber).putInt("soc_red", socRed)
                .putInt("screen_off", screenOffS).putInt("theme", theme).putInt("orientation", orientation)
                .putBoolean("keep_awake", keepAwake).putBoolean("full_screen", fullScreen)
                .putString("passthrough", passthrough)
                .apply();
    }

    public Settings copy() {
        Settings s = new Settings();
        s.mac = mac; s.key = key; s.demo = demo; s.staleAfterS = staleAfterS; s.socAmber = socAmber;
        s.socRed = socRed; s.screenOffS = screenOffS; s.theme = theme; s.orientation = orientation;
        s.keepAwake = keepAwake; s.fullScreen = fullScreen; s.passthrough = passthrough;
        s.chargerMac = chargerMac.clone(); s.chargerKey = chargerKey.clone(); s.otherSource = otherSource; s.loadsIcon = loadsIcon;
        return s;
    }

    /** True if charger slot {@code i} has both a MAC address and a key. */
    public boolean chargerUsed(int i) { return !chargerMac[i].isEmpty() && !chargerKey[i].isEmpty(); }

    /** Number of charger slots in use. */
    public int chargerCount() {
        int n = 0;
        for (int i = 0; i < CHARGER_SLOTS; i++) if (chargerUsed(i)) n++;
        return n;
    }

    /** True until a real MAC address and key have been entered. */
    public boolean needsSetup() {
        return mac.isEmpty() || key.isEmpty() || mac.equals("aa:bb:cc:dd:ee:ff")
                || key.equals("0123456789abcdef0123456789abcdef");
    }

    // ------------------------------------------------------------ validation helpers

    /**
     * Keeps only hex digits (ignoring : - space .), lower-cased. Returns null on any other
     * character or if the digit count isn't exactly {@code want}.
     */
    public static String hexOnly(String val, int want) {
        if (val == null) return null;
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < val.length(); i++) {
            char c = val.charAt(i);
            if (c == ':' || c == '-' || c == ' ' || c == '.') continue;
            if (Character.digit(c, 16) < 0 || b.length() >= want) return null;
            b.append(Character.toLowerCase(c));
        }
        return b.length() == want ? b.toString() : null;
    }

    /** "c03b12345678" or any separator style -> "c0:3b:12:34:56:78", or null if invalid. */
    public static String normaliseMac(String val) {
        String h = hexOnly(val, 12);
        if (h == null) return null;
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < 12; i += 2) { if (i > 0) b.append(':'); b.append(h, i, i + 2); }
        return b.toString();
    }

    public static String normaliseKey(String val) { return hexOnly(val, 32); }

    // ------------------------------------------------------------ CONFIG.TXT

    /** Result of reading a CONFIG.TXT. */
    public static final class ImportResult {
        public final Settings settings;
        public final int badLines;
        ImportResult(Settings s, int bad) { settings = s; badLines = bad; }
    }

    /**
     * Applies one "name = value" setting. Returns false for unknown names or bad values,
     * using the same rules as the Arduino display.
     */
    boolean apply(String name, String val, StringBuilder pass, String originalLine) {
        name = name.toLowerCase(Locale.US);
        long n;
        try { n = Long.parseLong(val.trim()); } catch (NumberFormatException e) { n = Long.MIN_VALUE; }
        switch (name) {
            case "mac": { String m = normaliseMac(val); if (m == null) return false; mac = m; return true; }
            case "key": { String k = normaliseKey(val); if (k == null) return false; key = k; return true; }
            case "demo": if (n == Long.MIN_VALUE) return false; demo = n != 0; return true;
            case "stale_after": if (n < 2) return false; staleAfterS = (int) n; return true;
            case "soc_amber": if (n == Long.MIN_VALUE) return false; socAmber = (int) Math.max(0, Math.min(100, n)); return true;
            case "soc_red": if (n == Long.MIN_VALUE) return false; socRed = (int) Math.max(0, Math.min(100, n)); return true;
            case "screen_off": if (n < 0) return false; screenOffS = (int) n; return true;
            case "theme": if (n < 0 || n > 2) return false; theme = (int) n; return true;
            case "orientation": if (n < 0 || n > 3) return false; orientation = (int) n; return true;
            case "keep_awake": if (n == Long.MIN_VALUE) return false; keepAwake = n != 0; return true;
            case "full_screen": if (n == Long.MIN_VALUE) return false; fullScreen = n != 0; return true;
            case "charger1_mac": case "charger2_mac": {
                String m = val.trim().isEmpty() ? "" : normaliseMac(val);
                if (m == null) return false;
                chargerMac[name.charAt(7) - '1'] = m;
                return true;
            }
            case "charger1_key": case "charger2_key": {
                String k = val.trim().isEmpty() ? "" : normaliseKey(val);
                if (k == null) return false;
                chargerKey[name.charAt(7) - '1'] = k;
                return true;
            }
            case "loads_icon": {
                String v = val.trim().toLowerCase(Locale.US);
                for (String o : LOADS_ICONS) if (o.equals(v)) { loadsIcon = o; return true; }
                return false;
            }
            case "other_source": {
                String v = val.trim().toLowerCase(Locale.US);
                for (String o : OTHER_SOURCES) if (o.equals(v)) { otherSource = o; return true; }
                return false;
            }
            // Arduino-only settings: not used here, but kept so an export doesn't lose them
            case "rotation": case "lcd_chip": case "invert": case "touch_cal":
                pass.append(originalLine.trim()).append('\n');
                return true;
            default: return false;
        }
    }

    /** Reads CONFIG.TXT text on top of the current settings. */
    public ImportResult importConfig(String text) {
        Settings s = copy();
        StringBuilder pass = new StringBuilder();
        int bad = 0;
        for (String raw : text.split("\n")) {
            String line = raw;
            int hash = line.indexOf('#');
            if (hash >= 0) line = line.substring(0, hash);
            line = line.trim();
            if (line.isEmpty()) continue;
            int eq = line.indexOf('=');
            if (eq < 0) { bad++; continue; }
            if (!s.apply(line.substring(0, eq).trim(), line.substring(eq + 1).trim(), pass, line)) bad++;
        }
        s.passthrough = pass.toString();
        return new ImportResult(s, bad);
    }

    /** CONFIG.TXT for the Arduino display's SD card (only settings it understands). */
    public String exportConfig() {
        StringBuilder f = new StringBuilder();
        String nl = "\r\n";
        f.append("# SmartShunt display settings").append(nl)
         .append("# Exported from the Shunt Display Android app.").append(nl)
         .append("# Lines starting with # are ignored. Restart the display after editing.").append(nl).append(nl)
         .append("# From VictronConnect: SmartShunt > settings > ... > Product info >").append(nl)
         .append("# Instant readout via Bluetooth > Show").append(nl);
        if (!mac.isEmpty()) f.append("mac = ").append(mac).append(nl);
        if (!key.isEmpty()) f.append("key = ").append(key).append(nl);
        f.append(nl).append("# Extra Victron chargers (optional): Blue Smart IP22, SmartSolar MPPT or Orion XS,").append(nl)
         .append("# with Instant readout turned on. MAC and key from VictronConnect, as for the shunt.").append(nl);
        for (int i = 0; i < CHARGER_SLOTS; i++) {
            if (chargerMac[i].isEmpty() && chargerKey[i].isEmpty()) continue;
            f.append("charger").append(i + 1).append("_mac = ").append(chargerMac[i]).append(nl)
             .append("charger").append(i + 1).append("_key = ").append(chargerKey[i]).append(nl);
        }
        f.append("# Name for charging they don't account for: auto, dcdc, solar, mains or alternator").append(nl)
         .append("other_source = ").append(otherSource).append(nl);
        f.append(nl).append("# Picture on the Loads node: house, caravan or boat").append(nl)
         .append("loads_icon = ").append(loadsIcon).append(nl);
        f.append(nl).append("# 1 = show fake data (to test the screen), 0 = read the shunt").append(nl)
         .append("demo = ").append(demo ? 1 : 0).append(nl).append(nl)
         .append("# Seconds without data before showing 'No signal'").append(nl)
         .append("stale_after = ").append(staleAfterS).append(nl)
         .append("# State of charge colours: amber below this %, red below the next").append(nl)
         .append("soc_amber = ").append(socAmber).append(nl)
         .append("soc_red = ").append(socRed).append(nl).append(nl)
         .append("# Seconds without a touch before the screen goes dark (a tap wakes it). 0 = always on").append(nl)
         .append("screen_off = ").append(screenOffS).append(nl);
        if (!passthrough.isEmpty()) {
            f.append(nl).append("# Display-only settings (kept from the imported file)").append(nl);
            for (String l : passthrough.split("\n")) if (!l.trim().isEmpty()) f.append(l.trim()).append(nl);
        }
        return f.toString();
    }
}
