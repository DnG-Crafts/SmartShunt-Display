package dngsoftware.shuntdisplay;

import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.WindowManager;
import android.widget.Toast;

import java.util.Locale;

/** The dashboard screen. */
public class MainActivity extends Activity implements DashboardView.Listener, ShuntScanner.Listener {

    private static final int REQ_PERMISSIONS = 1;
    private static final long TICK_MS = 250;

    private Settings settings;
    private boolean darkTheme;
    private DashboardView view;
    private ShuntScanner scanner;
    private byte[] key;
    private final Handler handler = new Handler(Looper.getMainLooper());

    // live state
    private final ShuntReading reading = new ShuntReading();
    private long lastHeard = 0;          // elapsedRealtime of the last good packet (0 = never)
    private int lastRssi;
    private long lastBadKey = 0;
    private int scanError = 0;
    private long scanStartedAt = 0;
    private boolean permissionAsked = false;
    private String source = null;        // which data we're showing: demo, or a MAC and key

    /** An extra Victron charger: what was last heard from it. */
    private static final class ChargerSlot {
        byte[] key;
        ChargerReading reading;
        long heard, badKey;                  // elapsedRealtime; 0 = never
    }
    private final ChargerSlot[] chargers = new ChargerSlot[Settings.CHARGER_SLOTS];

    // ------------------------------------------------------------ lifecycle

    private String language;             // the app language this screen was built with (Android 12 and older)

    @Override protected void attachBaseContext(android.content.Context base) { super.attachBaseContext(base); Lang.apply(this, base); }

    @Override protected void onCreate(Bundle saved) {
        language = Lang.get(this);
        settings = Settings.load(this);
        Ui.applyTheme(this, settings);
        darkTheme = Ui.isDark(this, settings);
        super.onCreate(saved);
        Ui.edgeToEdge(this);
        view = new DashboardView(this);
        view.setListener(this);
        setContentView(view);
        Ui.padForSystemBars(view);
        scanner = new ShuntScanner(this);
        for (int i = 0; i < chargers.length; i++) chargers[i] = new ChargerSlot();
    }

    @Override protected void onStart() {
        super.onStart();
        Settings fresh = Settings.load(this);
        // Theme changed in settings (or the phone switched dark mode): rebuild with the new colours
        if (Ui.isDark(this, fresh) != darkTheme) { settings = fresh; recreate(); return; }
        // Language changed in settings. Android 13+ restarts the screen itself; older versions need this.
        if (android.os.Build.VERSION.SDK_INT < 33 && !Lang.get(this).equals(language)) { recreate(); return; }
        settings = fresh;
        // New data source (demo switched, or a different shunt/key): forget the old readings
        String newSource = settings.demo ? "demo" : settings.mac + "/" + settings.key;
        for (int i = 0; i < chargers.length; i++) newSource += "/" + settings.chargerMac[i] + "/" + settings.chargerKey[i];
        if (!newSource.equals(source)) {
            source = newSource;
            copy(new ShuntReading(), reading);
            lastHeard = 0; lastBadKey = 0; scanError = 0;
            for (int i = 0; i < chargers.length; i++) {
                chargers[i] = new ChargerSlot();
                chargers[i].key = settings.chargerUsed(i) ? VictronDecoder.parseKey(settings.chargerKey[i]) : null;
            }
        }
        Ui.applyOrientation(this, settings);
        applyKeepAwake();
        Ui.setFullScreen(this, settings.fullScreen);
        key = VictronDecoder.parseKey(settings.key);
        registerReceiver(btReceiver, new IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED));
        startScanning();
        handler.post(tick);
    }

    @Override protected void onStop() {
        super.onStop();
        handler.removeCallbacks(tick);
        scanner.stop();
        try { unregisterReceiver(btReceiver); } catch (IllegalArgumentException ignored) { }
    }

    /** Dialogs, the keyboard or a notification shade can bring the bars back; hide them again. */
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus && settings != null) Ui.setFullScreen(this, settings.fullScreen);
    }

    private void applyKeepAwake() {
        if (settings.keepAwake) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    // ------------------------------------------------------------ scanning

    private boolean wantsBluetooth() { return !settings.demo && !settings.needsSetup(); }

    private void startScanning() {
        scanner.stop();
        scanError = 0;
        if (!wantsBluetooth()) return;
        if (!ShuntScanner.hasPermissions(this)) {
            if (!permissionAsked) { permissionAsked = true; requestPermissions(ShuntScanner.requiredPermissions(), REQ_PERMISSIONS); }
            return;
        }
        scanStartedAt = SystemClock.elapsedRealtime();   // also paces retries if starting fails
        java.util.List<String> macs = new java.util.ArrayList<>();
        macs.add(settings.mac);
        for (int i = 0; i < chargers.length; i++) if (settings.chargerUsed(i)) macs.add(settings.chargerMac[i]);
        scanner.start(macs, this);
    }

    @Override public void onAdvert(String address, String name, byte[] data, int rssi) {
        for (int i = 0; i < chargers.length; i++) {
            if (!settings.chargerUsed(i) || !address.equalsIgnoreCase(settings.chargerMac[i])) continue;
            ChargerReading cr = new ChargerReading();
            VictronDecoder.Result res = VictronDecoder.decodeCharger(data, chargers[i].key, cr);
            if (res == VictronDecoder.Result.OK) { chargers[i].reading = cr; chargers[i].heard = SystemClock.elapsedRealtime(); }
            else if (res == VictronDecoder.Result.BAD_KEY) chargers[i].badKey = SystemClock.elapsedRealtime();
        }
        if (!address.equalsIgnoreCase(settings.mac)) return;
        ShuntReading r = new ShuntReading();
        VictronDecoder.Result res = VictronDecoder.decode(data, key, r);
        if (res == VictronDecoder.Result.OK) {
            copy(r, reading);
            lastHeard = SystemClock.elapsedRealtime();
            lastRssi = rssi;
            scanError = 0;
        } else if (res == VictronDecoder.Result.BAD_KEY) {
            lastBadKey = SystemClock.elapsedRealtime();
        }
    }

    @Override public void onScanFailed(int errorCode) { scanError = errorCode; }

    private final BroadcastReceiver btReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            int st = i.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
            if (st == BluetoothAdapter.STATE_ON) startScanning();
            else if (st == BluetoothAdapter.STATE_TURNING_OFF || st == BluetoothAdapter.STATE_OFF) scanner.stop();
        }
    };

    @Override public void onRequestPermissionsResult(int req, String[] perms, int[] results) {
        super.onRequestPermissionsResult(req, perms, results);
        if (req == REQ_PERMISSIONS) startScanning();
    }

    private static void copy(ShuntReading a, ShuntReading b) {
        b.voltage = a.voltage; b.current = a.current; b.soc = a.soc; b.consumedAh = a.consumedAh;
        b.remainingMins = a.remainingMins; b.alarm = a.alarm; b.auxMode = a.auxMode; b.aux = a.aux; b.modelId = a.modelId;
    }

    // ------------------------------------------------------------ periodic update

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            long now = SystemClock.elapsedRealtime();
            if (settings.demo) demoTick(now);

            // Watchdog: if the shunt has been quiet for a minute, restart the scan (at most once a minute)
            if (wantsBluetooth() && scanner.isRunning() && now - Math.max(lastHeard, scanStartedAt) > 60_000) {
                startScanning();
            }
            // Bluetooth, permission or location came back while we weren't scanning
            if (wantsBluetooth() && !scanner.isRunning() && ShuntScanner.hasPermissions(MainActivity.this)
                    && ShuntScanner.isBluetoothOn(MainActivity.this) && now - scanStartedAt > 5_000) {
                startScanning();
            }

            boolean stale = lastHeard == 0 || now - lastHeard > settings.staleAfterS * 1000L;

            view.setState(buildState(now, stale));
            handler.postDelayed(this, TICK_MS);
        }
    };

    private void demoTick(long now) {
        float t = now / 1000f;
        float cur = -8.5f + 14 * (float) Math.sin(t / 20);
        reading.current = cur;
        reading.voltage = 13.1f + 0.02f * cur;
        reading.soc = 78.4f - (t / 60) % 20;
        reading.consumedAh = -21.6f;
        reading.remainingMins = cur > 0 ? -1 : 1234;
        reading.alarm = 0;
        reading.auxMode = ShuntReading.AUX_STARTER;
        reading.aux = 12.6f;
        lastHeard = now;
        lastRssi = -67;
        // configured chargers: a mains charger that comes and goes, a solar charger with the sun
        for (int i = 0; i < chargers.length; i++) {
            if (!settings.chargerUsed(i)) continue;
            ChargerReading cr = new ChargerReading();
            cr.kind = chargers[i].reading != null ? chargers[i].reading.kind : ChargerReading.KIND_MAINS;
            boolean mains = cr.kind == ChargerReading.KIND_MAINS;
            float watts = Math.max(0f, (mains ? 400 : 180) * (float) Math.sin(t / (mains ? 35 : 50)));
            cr.voltage = reading.voltage;
            cr.current = watts / cr.voltage;
            cr.power = watts;
            cr.state = watts <= 0 ? 0 : watts < 150 ? 5 : 3;
            cr.error = 0;
            chargers[i].reading = cr;
            chargers[i].heard = now;
            reading.current += cr.current;
        }
    }

    // ------------------------------------------------------------ what to show

    private DashboardView.State buildState(long now, boolean stale) {
        DashboardView.State s = new DashboardView.State();
        ShuntReading r = reading;
        int txt = stale ? DashboardView.MUTED : DashboardView.TEXT;
        s.stale = stale;
        String model = VictronDecoder.modelName(r.modelId);
        s.title = model != null && model.startsWith("BMV") ? model.split(" ")[0] : "SmartShunt";

        s.soc = Float.isNaN(r.soc) ? "--" : String.valueOf(Math.round(r.soc));
        s.socColor = stale || Float.isNaN(r.soc) ? DashboardView.MUTED
                : r.soc >= settings.socAmber ? DashboardView.GOOD
                : r.soc >= settings.socRed ? DashboardView.WARN : DashboardView.BAD;
        s.barPercent = Float.isNaN(r.soc) ? -1 : r.soc;
        s.level = Float.isNaN(r.soc) ? -1 : r.soc;

        float cur = r.current, pw = r.power();              // + charging, - discharging
        boolean known = !Float.isNaN(pw);
        boolean charging = known && pw > DashboardView.IDLE_W, discharging = known && pw < -DashboardView.IDLE_W;
        boolean full = !Float.isNaN(r.soc) && r.soc >= 99.5f;

        // Time left (the shunt's own estimate), or the battery's state
        if (discharging) {
            s.timeLabel = getString(R.string.dash_time_left);
            if (r.remainingMins < 0) s.time = "--";
            else {
                int m = r.remainingMins, d = m / 1440, h = (m % 1440) / 60, mm = m % 60;
                s.time = d > 0 ? getString(R.string.time_days_hours, d, h) : getString(R.string.time_hours_minutes, h, mm);
            }
        } else {
            s.timeLabel = getString(R.string.dash_battery);
            s.time = !known ? "--" : getString(full ? R.string.time_full : charging ? R.string.time_charging : R.string.time_idle);
        }

        // Flow picture: + toward the hub
        java.util.List<DashboardView.Node> nodes = flowNodes(pw, now);
        nodes.add(new DashboardView.Node(DashboardView.BOTTOM, DashboardView.C_BATTERY, DashboardView.BATTERY, fmtPower(pw),
                getString(charging ? R.string.time_charging : discharging ? R.string.dash_discharging : R.string.dash_battery),
                known ? -pw : Float.NaN, fmt(r.voltage, 2, " V", false), DashboardView.MUTED));
        s.nodes = nodes.toArray(new DashboardView.Node[0]);

        // Readings
        int curCol = stale || Float.isNaN(cur) ? DashboardView.MUTED
                : cur > 0.05f ? DashboardView.GOOD : cur < -0.05f ? DashboardView.WARN : DashboardView.TEXT;
        s.voltage = fmt(r.voltage, 2, " V", false);
        s.current = fmt(cur, 1, " A", true);
        setReading(s, 0, DashboardView.I_VOLT, DashboardView.C_CHARGER, R.string.dash_voltage, s.voltage, txt);
        setReading(s, 1, DashboardView.I_AMP, DashboardView.C_LOADS, R.string.dash_current, s.current, curCol);
        setReading(s, 2, DashboardView.I_POWER, DashboardView.C_ACCENT, R.string.dash_power, fmt(pw, 0, " W", true), curCol);
        setReading(s, 3, DashboardView.I_CONSUMED, DashboardView.C_BATTERY, R.string.dash_consumed, fmt(r.consumedAh, 1, " Ah", false), txt);
        if (r.auxMode == ShuntReading.AUX_STARTER)
            setReading(s, 4, DashboardView.I_STARTER, DashboardView.C_CHARGER, R.string.dash_starter, fmt(r.aux, 2, " V", false), txt);
        else if (r.auxMode == ShuntReading.AUX_MIDPOINT)
            setReading(s, 4, DashboardView.I_MIDPOINT, DashboardView.C_BATTERY, R.string.dash_midpoint, fmt(r.aux, 2, " V", false), txt);
        else
            setReading(s, 4, DashboardView.I_TEMP, DashboardView.C_ACCENT, R.string.dash_temp, fmt(r.aux, 0, " °C", false), txt);
        setReading(s, 5, DashboardView.I_SIGNAL, DashboardView.C_LOADS, R.string.dash_signal,
                lastHeard != 0 && lastRssi != 0 ? lastRssi + " dBm" : "--", txt);

        // Status: the first problem that applies (same order as the Arduino display)
        long age = (now - lastHeard) / 1000;
        boolean badKey = key == null || (lastBadKey != 0 && now - lastBadKey < 10_000 && stale);
        if (settings.needsSetup() && !settings.demo) status(s, R.string.st_setup, DashboardView.WARN, getString(R.string.st_setup_detail));
        else if (settings.demo) status(s, R.string.st_ok, DashboardView.GOOD, getString(R.string.st_demo_detail));
        else if (!ShuntScanner.hasBluetooth(this)) status(s, R.string.st_no_ble, DashboardView.BAD, getString(R.string.st_no_ble_detail));
        else if (!ShuntScanner.hasPermissions(this)) status(s, R.string.st_permission, DashboardView.WARN, getString(R.string.st_permission_detail));
        else if (!ShuntScanner.isBluetoothOn(this)) status(s, R.string.st_bt_off, DashboardView.WARN, getString(R.string.st_bt_off_detail));
        else if (ShuntScanner.isLocationOffButNeeded(this)) status(s, R.string.st_location_off, DashboardView.WARN, getString(R.string.st_location_off_detail));
        else if (scanError != 0) status(s, R.string.st_ble_fail, DashboardView.BAD, getString(R.string.st_ble_fail_detail, scanError));
        else if (badKey) status(s, R.string.st_bad_key, DashboardView.BAD, getString(R.string.st_bad_key_detail));
        else if (lastHeard == 0) status(s, R.string.st_searching, DashboardView.WARN, "");
        else if (stale) status(s, R.string.st_no_signal, DashboardView.WARN, getString(R.string.st_age_short, age));
        else if (r.alarm != 0) status(s, R.string.st_alarm, DashboardView.BAD, alarmText(r.alarm));
        else status(s, R.string.st_ok, DashboardView.GOOD, getString(R.string.st_age_short, age));
        return s;
    }

    /**
     * The charge sources and the loads (the same rules as the Raspberry Pi version).
     *
     * The shunt measures only the battery (pw, + charging). Each extra Victron charger reports its
     * own output, so with K watts coming from them, the loads take K - pw when that's positive,
     * and anything the battery gets beyond K came from a charger the app can't hear (shown on the
     * "other" node). With no extra chargers it's the plain picture: charging comes from the
     * charger, discharging goes to the loads.
     */
    private java.util.List<DashboardView.Node> flowNodes(float pw, long now) {
        boolean known = !Float.isNaN(pw);
        java.util.List<DashboardView.Node> nodes = new java.util.ArrayList<>();
        int[] places = {DashboardView.LEFT, DashboardView.TOP};
        int[] colors = {DashboardView.C_ACCENT, DashboardView.C_CHARGER};
        int count = 0;
        float total = 0;
        for (int i = 0; i < chargers.length; i++) {
            if (!settings.chargerUsed(i)) continue;
            ChargerSlot c = chargers[i];
            ChargerReading cr = c.reading;
            boolean fresh = c.heard != 0 && now - c.heard <= settings.staleAfterS * 1000L;
            float watts = fresh && cr != null && !Float.isNaN(cr.power) ? Math.max(0, cr.power) : Float.NaN;
            if (!Float.isNaN(watts)) total += watts;
            int kind = cr != null ? cr.kind : -1;
            int icon = kind == ChargerReading.KIND_SOLAR ? DashboardView.I_SOLAR
                    : kind == ChargerReading.KIND_DCDC ? DashboardView.I_CAR : DashboardView.CHARGER;
            String label = kind == ChargerReading.KIND_MAINS ? getString(R.string.dash_mains)
                    : kind == ChargerReading.KIND_SOLAR ? getString(R.string.dash_solar)
                    : kind == ChargerReading.KIND_DCDC ? getString(R.string.dash_dcdc) : getString(R.string.charger_n, i + 1);
            String extra;
            int extraColor = DashboardView.MUTED;
            if (!fresh) {
                boolean badKey = c.key == null || (c.badKey != 0 && now - c.badKey < 10_000);
                extra = getString(badKey ? R.string.st_bad_key : c.heard != 0 ? R.string.st_no_signal : R.string.st_searching);
                extraColor = DashboardView.WARN;
            } else if (cr.error > 0) {
                extra = getString(R.string.charger_error, cr.error);
                extraColor = DashboardView.BAD;
            } else {
                extra = stageName(cr.state);
            }
            if (count < 2) nodes.add(new DashboardView.Node(places[count], colors[count], icon, fmtPower(watts), label,
                    Float.isNaN(watts) ? 0 : watts, extra, extraColor));
            count++;
        }
        float other, loads;
        if (count == 0) {
            other = known && pw > DashboardView.IDLE_W ? pw : 0;
            loads = known && pw < -DashboardView.IDLE_W ? -pw : 0;
        } else {
            other = Math.max(0, pw - total);
            loads = Math.max(0, total - pw);
        }
        if (!known) { other = Float.NaN; loads = Float.NaN; }
        if (count < 2) {
            String src = settings.otherSource;
            int label, icon;
            switch (src) {
                case "dcdc": label = R.string.dash_dcdc; icon = DashboardView.I_CAR; break;
                case "alternator": label = R.string.dash_alternator; icon = DashboardView.I_CAR; break;
                case "solar": label = R.string.dash_solar; icon = DashboardView.I_SOLAR; break;
                case "mains": label = R.string.dash_mains; icon = DashboardView.CHARGER; break;
                default:     // not a plug next to a mains charger's plug
                    label = count > 0 ? R.string.dash_other : R.string.dash_charger;
                    icon = count > 0 ? DashboardView.I_VOLT : DashboardView.CHARGER;
            }
            nodes.add(new DashboardView.Node(DashboardView.TOP, DashboardView.C_CHARGER, icon, fmtPower(other),
                    getString(label), other, "", DashboardView.MUTED));
        }
        int loadsIcon = "caravan".equals(settings.loadsIcon) ? DashboardView.I_CARAVAN
                : "boat".equals(settings.loadsIcon) ? DashboardView.I_BOAT : DashboardView.LOADS;
        nodes.add(new DashboardView.Node(DashboardView.RIGHT, DashboardView.C_LOADS, loadsIcon, fmtPower(loads),
                getString(R.string.dash_loads), -loads, "", DashboardView.MUTED));
        return nodes;
    }

    /** A Victron charger's operation mode as a charge stage ("Bulk", "Float"…), or "". */
    private String stageName(int state) {
        switch (state) {
            case 0: case 1: return getString(R.string.stage_off);
            case 2: return getString(R.string.stage_fault);
            case 3: return getString(R.string.stage_bulk);
            case 4: case 246: case 248: return getString(R.string.stage_absorption);
            case 5: return getString(R.string.stage_float);
            case 6: return getString(R.string.stage_storage);
            case 7: case 247: return getString(R.string.stage_recondition);
            case 11: return getString(R.string.stage_psu);
            case 245: return getString(R.string.stage_starting);
            default: return "";
        }
    }

    private void setReading(DashboardView.State s, int i, int icon, int iconColor, int label, String value, int valueColor) {
        s.readIcon[i] = icon;
        s.readIconColor[i] = iconColor;
        s.readLabel[i] = getString(label);
        s.readValue[i] = value;
        s.readValueColor[i] = "--".equals(value) ? DashboardView.MUTED : valueColor;
    }

    /** Watts without a sign: "456 W", "4.91 kW", "12.4 kW" (the same rules as the other versions). */
    private String fmtPower(float w) {
        if (Float.isNaN(w)) return "--";
        int a = (int) (Math.abs(w) + 0.5f);
        if (a < 1000) return a + " W";
        String n = a < 9995 ? String.format(Locale.US, "%d.%02d", (a + 5) / 10 / 100, (a + 5) / 10 % 100)
                : String.format(Locale.US, "%d.%d", (a + 50) / 100 / 10, (a + 50) / 100 % 10);
        Locale lang = getResources().getConfiguration().getLocales().get(0);
        if (java.text.DecimalFormatSymbols.getInstance(lang).getDecimalSeparator() == ',') n = n.replace('.', ',');
        return n + " kW";
    }

    private void status(DashboardView.State s, int word, int color, String detail) {
        s.status = getString(word); s.statusColor = color; s.detail = detail;
    }

    /** The first active alarm by name, plus "+n" when there are more (like the Arduino display). */
    private String alarmText(int alarm) {
        String[] names = getResources().getStringArray(R.array.alarm_names);
        String first = null;
        int count = 0;
        for (int i = 0; i < names.length; i++) {
            if ((alarm & (1 << i)) != 0) { if (first == null) first = names[i]; count++; }
        }
        if (first == null) return getString(R.string.alarm_code, String.format(Locale.US, "0x%04X", alarm));
        return count > 1 ? first + " +" + (count - 1) : first;
    }

    /**
     * Formats a reading with Western digits and the language's decimal separator (12.66 or 12,66),
     * so numbers stay easy to read at a glance in every language.
     */
    private String fmt(float v, int decimals, String unit, boolean sign) {
        if (Float.isNaN(v)) return "--";
        String n = String.format(Locale.US, "%." + decimals + "f", v);
        if (sign && v > 0 && !n.startsWith("+")) n = "+" + n;
        if (n.equals("-0") || n.matches("-0\\.0+")) n = n.substring(1);
        Locale lang = getResources().getConfiguration().getLocales().get(0);
        if (java.text.DecimalFormatSymbols.getInstance(lang).getDecimalSeparator() == ',') n = n.replace('.', ',');
        return n + unit;
    }

    // ------------------------------------------------------------ touch

    @Override public void onCogTapped() { startActivity(new Intent(this, SettingsActivity.class)); }

    @Override public void onStatusTapped() {
        if (settings.needsSetup() && !settings.demo) { onCogTapped(); return; }
        if (!wantsBluetooth()) return;
        if (!ShuntScanner.hasPermissions(this)) {
            if (shouldShowAnyRationale() || !permissionAsked) {
                permissionAsked = true;
                requestPermissions(ShuntScanner.requiredPermissions(), REQ_PERMISSIONS);
            } else {
                // Permanently denied: the only way back is the app's system settings page
                startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        android.net.Uri.fromParts("package", getPackageName(), null)));
                Toast.makeText(this, R.string.allow_nearby_devices, Toast.LENGTH_LONG).show();
            }
        } else if (!ShuntScanner.isBluetoothOn(this)) {
            startActivity(new Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS));
        } else if (ShuntScanner.isLocationOffButNeeded(this)) {
            startActivity(new Intent(android.provider.Settings.ACTION_LOCATION_SOURCE_SETTINGS));
        }
    }

    private boolean shouldShowAnyRationale() {
        for (String p : ShuntScanner.requiredPermissions()) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED && shouldShowRequestPermissionRationale(p)) return true;
        }
        return false;
    }
}
