package dngsoftware.shuntdisplay;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipDescription;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.RadioGroup;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Settings: same options as the Arduino display, plus theme, orientation and keep-awake. */
public class SettingsActivity extends Activity {

    private static final int REQ_FIND = 1, REQ_EXPORT = 2, REQ_IMPORT = 3, REQ_FIND_CHARGER = 10;   // + slot
    private static final int STALE_MIN = 5, STALE_MAX = 600, STEP = 5;

    private Settings original;
    private String passthrough;

    private EditText mac, key;
    private final EditText[] chargerMac = new EditText[Settings.CHARGER_SLOTS];
    private final EditText[] chargerKey = new EditText[Settings.CHARGER_SLOTS];
    private Spinner otherSource, loadsIcon;
    private Switch demo, keepAwake, fullScreen;
    private RadioGroup theme;
    private Spinner orientation, language;
    private String[] languageTags;     // the picker's languages; position 0 is "System default"
    private int languageOriginal;
    private SeekBar stale, amber, red;
    private TextView staleValue, amberValue, redValue;
    private View clipBanner;
    private TextView clipText;
    private String clipKind, clipValue;   // what the clipboard banner offers: "key" or "mac"
    private int clipSlot = -1;            // ... for the shunt (-1) or a charger slot

    @Override protected void attachBaseContext(Context base) { super.attachBaseContext(base); Lang.apply(this, base); }

    @Override protected void onCreate(Bundle saved) {
        original = Settings.load(this);
        Ui.applyTheme(this, original);
        super.onCreate(saved);
        Ui.edgeToEdge(this);
        setContentView(R.layout.activity_settings);
        Ui.padForSystemBars(findViewById(R.id.root));
        Ui.limitContentWidth(findViewById(R.id.content), 720);

        mac = findViewById(R.id.mac);
        key = findViewById(R.id.key);
        demo = findViewById(R.id.demo);
        keepAwake = findViewById(R.id.keep_awake);
        fullScreen = findViewById(R.id.full_screen);
        theme = findViewById(R.id.theme);
        orientation = findViewById(R.id.orientation);
        language = findViewById(R.id.language);
        stale = findViewById(R.id.stale);
        amber = findViewById(R.id.amber);
        red = findViewById(R.id.red);
        staleValue = findViewById(R.id.stale_value);
        amberValue = findViewById(R.id.amber_value);
        redValue = findViewById(R.id.red_value);
        clipBanner = findViewById(R.id.clip_banner);
        otherSource = findViewById(R.id.other_source);
        loadsIcon = findViewById(R.id.loads_icon);
        loadsIcon.setAdapter(adapter(new String[]{getString(R.string.icon_house), getString(R.string.icon_caravan),
                getString(R.string.icon_boat)}));
        int[][] ids = {{R.id.charger1_title, R.id.charger1_mac, R.id.charger1_key, R.id.charger1_find, R.id.charger1_paste},
                       {R.id.charger2_title, R.id.charger2_mac, R.id.charger2_key, R.id.charger2_find, R.id.charger2_paste}};
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            final int slot = i;
            ((TextView) findViewById(ids[i][0])).setText(getString(R.string.charger_n, i + 1));
            chargerMac[i] = findViewById(ids[i][1]);
            chargerKey[i] = findViewById(ids[i][2]);
            findViewById(ids[i][3]).setOnClickListener(v -> startActivityForResult(
                    new Intent(this, DeviceScanActivity.class).putExtra(DeviceScanActivity.EXTRA_CHARGERS, true),
                    REQ_FIND_CHARGER + slot));
            findViewById(ids[i][4]).setOnClickListener(v -> pasteKey(chargerKey[slot]));
        }
        otherSource.setAdapter(adapter(new String[]{getString(R.string.source_auto), getString(R.string.dash_dcdc),
                getString(R.string.dash_solar), getString(R.string.dash_mains), getString(R.string.dash_alternator)}));
        clipText = findViewById(R.id.clip_text);

        orientation.setAdapter(adapter(getResources().getStringArray(R.array.orientations)));
        languageTags = getResources().getStringArray(R.array.language_tags);
        String[] names = getResources().getStringArray(R.array.language_names);
        String[] choices = new String[names.length + 1];
        choices[0] = getString(R.string.language_system);
        System.arraycopy(names, 0, choices, 1, names.length);
        language.setAdapter(adapter(choices));
        languageOriginal = Lang.indexOf(languageTags, Lang.get(this)) + 1;   // 0 = system default
        language.setSelection(saved != null ? saved.getInt("language", languageOriginal) : languageOriginal);

        stale.setMax((STALE_MAX - STALE_MIN) / STEP);
        amber.setMax(100 / STEP);
        red.setMax(100 / STEP);
        SeekBar.OnSeekBarChangeListener update = new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar s, int p, boolean user) { showSliderValues(); }
            @Override public void onStartTrackingTouch(SeekBar s) { }
            @Override public void onStopTrackingTouch(SeekBar s) { }
        };
        stale.setOnSeekBarChangeListener(update);
        amber.setOnSeekBarChangeListener(update);
        red.setOnSeekBarChangeListener(update);

        findViewById(R.id.cancel).setOnClickListener(v -> leave());
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            // Android 13+: predictive back (onBackPressed isn't called when targeting Android 16)
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::leave);
        }
        findViewById(R.id.save).setOnClickListener(v -> save());
        findViewById(R.id.find).setOnClickListener(v ->
                startActivityForResult(new Intent(this, DeviceScanActivity.class), REQ_FIND));
        findViewById(R.id.paste).setOnClickListener(v -> pasteKey(key));
        findViewById(R.id.clip_use).setOnClickListener(v -> {
            useClip();
            hideClipBanner();
        });
        findViewById(R.id.clip_dismiss).setOnClickListener(v -> hideClipBanner());
        findViewById(R.id.export).setOnClickListener(v -> startExport());
        findViewById(R.id.import_config).setOnClickListener(v -> startImport());
        ((TextView) findViewById(R.id.about)).setText(getString(R.string.about, versionName()));

        show(saved != null ? restore(saved) : original);
        if (saved != null && saved.getString("clip_kind") != null)
            offerClip(saved.getString("clip_kind"), saved.getString("clip_value"));
    }

    private ArrayAdapter<String> adapter(String[] items) {
        ArrayAdapter<String> a = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, items);
        a.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        return a;
    }

    // ------------------------------------------------------------ form <-> settings

    private void show(Settings s) {
        passthrough = s.passthrough;
        mac.setText(s.mac);
        key.setText(s.key);
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            chargerMac[i].setText(s.chargerMac[i]);
            chargerKey[i].setText(s.chargerKey[i]);
        }
        loadsIcon.setSelection(Math.max(0, java.util.Arrays.asList(Settings.LOADS_ICONS).indexOf(s.loadsIcon)));
        otherSource.setSelection(Math.max(0, java.util.Arrays.asList(Settings.OTHER_SOURCES).indexOf(s.otherSource)));
        demo.setChecked(s.demo);
        keepAwake.setChecked(s.keepAwake);
        fullScreen.setChecked(s.fullScreen);
        theme.check(s.theme == Settings.THEME_LIGHT ? R.id.theme_light
                : s.theme == Settings.THEME_DARK ? R.id.theme_dark : R.id.theme_system);
        orientation.setSelection(Math.max(0, Math.min(3, s.orientation)));
        stale.setProgress((Math.max(STALE_MIN, Math.min(STALE_MAX, s.staleAfterS)) - STALE_MIN) / STEP);
        amber.setProgress(s.socAmber / STEP);
        red.setProgress(s.socRed / STEP);
        showSliderValues();
    }

    private void showSliderValues() {
        staleValue.setText(getString(R.string.seconds_value, STALE_MIN + stale.getProgress() * STEP));
        amberValue.setText(getString(R.string.percent_value, amber.getProgress() * STEP));
        redValue.setText(getString(R.string.percent_value, red.getProgress() * STEP));
    }

    /** Reads the form. MAC/key are kept as typed here; {@link #validate} normalises them. */
    private Settings read() {
        Settings s = original.copy();
        s.mac = mac.getText().toString().trim();
        s.key = key.getText().toString().trim();
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            s.chargerMac[i] = chargerMac[i].getText().toString().trim();
            s.chargerKey[i] = chargerKey[i].getText().toString().trim();
        }
        s.loadsIcon = Settings.LOADS_ICONS[Math.max(0, loadsIcon.getSelectedItemPosition())];
        s.otherSource = Settings.OTHER_SOURCES[Math.max(0, otherSource.getSelectedItemPosition())];
        s.demo = demo.isChecked();
        s.keepAwake = keepAwake.isChecked();
        s.fullScreen = fullScreen.isChecked();
        int t = theme.getCheckedRadioButtonId();
        s.theme = t == R.id.theme_light ? Settings.THEME_LIGHT : t == R.id.theme_dark ? Settings.THEME_DARK : Settings.THEME_SYSTEM;
        s.orientation = orientation.getSelectedItemPosition();
        s.staleAfterS = STALE_MIN + stale.getProgress() * STEP;
        s.socAmber = amber.getProgress() * STEP;
        s.socRed = red.getProgress() * STEP;
        s.passthrough = passthrough;
        return s;
    }

    /** Normalises the MAC addresses and keys; shows an error and returns false if any is malformed. */
    private boolean validate(Settings s) {
        EditText bad = null;
        String m = check(s.mac, true, mac);
        String k = check(s.key, false, key);
        if (m == null) bad = mac; else s.mac = m;
        if (k == null) { if (bad == null) bad = key; } else s.key = k;
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            m = check(s.chargerMac[i], true, chargerMac[i]);
            k = check(s.chargerKey[i], false, chargerKey[i]);
            if (m == null) { if (bad == null) bad = chargerMac[i]; } else s.chargerMac[i] = m;
            if (k == null) { if (bad == null) bad = chargerKey[i]; } else s.chargerKey[i] = k;
        }
        if (bad != null) bad.requestFocus();
        return bad == null;
    }

    /** A normalised MAC address or key ("" stays ""), or null after showing an error on {@code field}. */
    private String check(String value, boolean isMac, EditText field) {
        if (value.isEmpty()) return "";
        String n = isMac ? Settings.normaliseMac(value) : Settings.normaliseKey(value);
        if (n == null) field.setError(getString(isMac ? R.string.mac_error : R.string.key_error));
        return n;
    }

    /** Like validate(), for comparing: normalises what it can and leaves the rest as typed. */
    private static void normaliseLoosely(Settings s) {
        String m = Settings.normaliseMac(s.mac), k = Settings.normaliseKey(s.key);
        if (m != null) s.mac = m;
        if (k != null) s.key = k;
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            m = Settings.normaliseMac(s.chargerMac[i]);
            k = Settings.normaliseKey(s.chargerKey[i]);
            if (m != null) s.chargerMac[i] = m;
            if (k != null) s.chargerKey[i] = k;
        }
    }

    private void save() {
        Settings s = read();
        if (!validate(s)) return;
        s.save(this);
        Toast.makeText(this, R.string.saved, Toast.LENGTH_SHORT).show();
        finish();
        int lang = language.getSelectedItemPosition();
        if (lang != languageOriginal) Lang.set(this, lang == 0 ? "" : languageTags[lang - 1]);
    }

    @SuppressWarnings("deprecation")
    @Override public void onBackPressed() { leave(); }   // Android 12 and older

    /** Back or Cancel: asks before throwing away edits. */
    private void leave() {
        Settings now = read();
        normaliseLoosely(now);
        boolean changed = !now.exportConfig().equals(original.exportConfig())
                || now.theme != original.theme || now.orientation != original.orientation || now.keepAwake != original.keepAwake
                || now.fullScreen != original.fullScreen
                || language.getSelectedItemPosition() != languageOriginal;
        if (!changed) { finish(); return; }
        new AlertDialog.Builder(this)
                .setMessage(R.string.discard_changes)
                .setPositiveButton(R.string.discard, (d, w) -> finish())
                .setNegativeButton(R.string.keep_editing, null)
                .show();
    }

    // Keep typed values across rotation
    @Override protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putString("config", read().exportConfig());
        Settings s = read();
        out.putInt("theme", s.theme); out.putInt("orientation", s.orientation); out.putBoolean("keep_awake", s.keepAwake);
        out.putBoolean("full_screen", s.fullScreen);
        out.putInt("language", language.getSelectedItemPosition());
        out.putString("mac_raw", mac.getText().toString()); out.putString("key_raw", key.getText().toString());
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            out.putString("charger_mac_raw" + i, chargerMac[i].getText().toString());
            out.putString("charger_key_raw" + i, chargerKey[i].getText().toString());
        }
        out.putInt("clip_slot", clipSlot);
        out.putString("clip_kind", clipKind); out.putString("clip_value", clipValue);
    }

    private Settings restore(Bundle b) {
        Settings s = original.importConfig(b.getString("config", "")).settings;
        s.theme = b.getInt("theme", s.theme); s.orientation = b.getInt("orientation", s.orientation);
        s.keepAwake = b.getBoolean("keep_awake", s.keepAwake);
        s.fullScreen = b.getBoolean("full_screen", s.fullScreen);
        s.mac = b.getString("mac_raw", s.mac); s.key = b.getString("key_raw", s.key);
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) {
            s.chargerMac[i] = b.getString("charger_mac_raw" + i, s.chargerMac[i]);
            s.chargerKey[i] = b.getString("charger_key_raw" + i, s.chargerKey[i]);
        }
        clipSlot = b.getInt("clip_slot", -1);
        return s;
    }

    // ------------------------------------------------------------ helpers

    private void pasteKey(EditText key) {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        ClipData clip = cm == null ? null : cm.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0 || clip.getItemAt(0).getText() == null) {
            Toast.makeText(this, R.string.clipboard_empty, Toast.LENGTH_SHORT).show();
            return;
        }
        String text = clip.getItemAt(0).getText().toString().trim();
        String k = Settings.normaliseKey(text);
        key.setText(k != null ? k : text);
        key.setError(k != null ? null : getString(R.string.key_error));
    }

    // ------------------------------------------------------------ clipboard detection

    private static final String CLIP_PREFS = "clipboard";

    /** Android only lets an app read the clipboard while it has focus, so check then. */
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) checkClipboard();
    }

    /**
     * Offers a key or MAC address found on the clipboard. The clipboard's timestamp is checked
     * first, and the text is only read when something new has been copied, because Android 12+
     * shows a "pasted from your clipboard" message every time an app reads it.
     */
    private void checkClipboard() {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (cm == null) return;
        ClipDescription desc = cm.getPrimaryClipDescription();
        if (desc == null || !(desc.hasMimeType("text/*"))) return;

        long stamp = desc.getTimestamp();
        android.content.SharedPreferences p = getSharedPreferences(CLIP_PREFS, MODE_PRIVATE);
        if (stamp != 0 && stamp == p.getLong("seen", 0)) return;   // already looked at this one
        p.edit().putLong("seen", stamp).apply();

        ClipData clip = cm.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) return;
        CharSequence cs = clip.getItemAt(0).getText();
        if (cs == null || cs.length() > 200) return;
        String text = cs.toString().trim();

        // for a charger if one of its fields was the last in use, otherwise for the shunt
        clipSlot = focusedCharger();
        EditText keyField = clipSlot < 0 ? key : chargerKey[clipSlot];
        EditText macField = clipSlot < 0 ? mac : chargerMac[clipSlot];
        String k = Settings.normaliseKey(text);
        if (k != null) {
            if (!k.equals(Settings.normaliseKey(keyField.getText().toString().trim()))) offerClip("key", k);
            return;
        }
        String m = Settings.normaliseMac(text);
        if (m != null) {
            if (!m.equals(Settings.normaliseMac(macField.getText().toString().trim()))) offerClip("mac", m);
        }
    }

    /** The charger slot whose MAC or key field has focus, or -1. */
    private int focusedCharger() {
        View f = getCurrentFocus();
        for (int i = 0; i < Settings.CHARGER_SLOTS; i++) if (f == chargerMac[i] || f == chargerKey[i]) return i;
        return -1;
    }

    /** Shows the banner offering a normalised key or MAC address. */
    private void offerClip(String kind, String value) {
        if (value == null) return;
        clipKind = kind;
        clipValue = value;
        clipText.setText("key".equals(kind)
                ? getString(R.string.clip_key_found, value.substring(0, 4) + "…" + value.substring(28))
                : getString(R.string.clip_mac_found, value.toUpperCase(java.util.Locale.US)));
        clipBanner.setVisibility(View.VISIBLE);
    }

    private void useClip() {
        EditText keyField = clipSlot < 0 ? key : chargerKey[clipSlot];
        EditText macField = clipSlot < 0 ? mac : chargerMac[clipSlot];
        if ("key".equals(clipKind)) { keyField.setText(clipValue); keyField.setError(null); }
        else if ("mac".equals(clipKind)) { macField.setText(clipValue); macField.setError(null); }
    }

    private void hideClipBanner() {
        clipKind = null;
        clipValue = null;
        clipBanner.setVisibility(View.GONE);
    }

    private String versionName() {
        try {
            PackageInfo pi = getPackageManager().getPackageInfo(getPackageName(), 0);
            return pi.versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    // ------------------------------------------------------------ CONFIG.TXT export / import

    private void startExport() {
        Settings s = read();
        if (!validate(s)) return;
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("text/plain");
        i.putExtra(Intent.EXTRA_TITLE, "CONFIG.TXT");
        startActivityForResult(i, REQ_EXPORT);
    }

    private void startImport() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("text/*");
        startActivityForResult(i, REQ_IMPORT);
    }

    @Override protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (result != RESULT_OK || data == null) return;
        if (req == REQ_FIND) {
            String found = data.getStringExtra(DeviceScanActivity.EXTRA_MAC);
            if (found != null) { mac.setText(found); mac.setError(null); key.requestFocus(); }
        } else if (req >= REQ_FIND_CHARGER && req < REQ_FIND_CHARGER + Settings.CHARGER_SLOTS) {
            int i = req - REQ_FIND_CHARGER;
            String found = data.getStringExtra(DeviceScanActivity.EXTRA_MAC);
            if (found != null) { chargerMac[i].setText(found); chargerMac[i].setError(null); chargerKey[i].requestFocus(); }
        } else if (req == REQ_EXPORT && data.getData() != null) {
            Settings s = read();
            if (!validate(s)) return;
            try (OutputStream out = getContentResolver().openOutputStream(data.getData(), "wt")) {
                if (out == null) throw new IOException("no stream");
                out.write(s.exportConfig().getBytes(StandardCharsets.UTF_8));
                Toast.makeText(this, R.string.exported, Toast.LENGTH_LONG).show();
            } catch (IOException | SecurityException e) {
                Toast.makeText(this, getString(R.string.export_failed, e.getMessage()), Toast.LENGTH_LONG).show();
            }
        } else if (req == REQ_IMPORT && data.getData() != null) {
            importFrom(data.getData());
        }
    }

    private void importFrom(Uri uri) {
        try (InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null) throw new IOException("no stream");
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[4096];
            int n;
            while ((n = in.read(chunk)) > 0 && buf.size() < 64 * 1024) buf.write(chunk, 0, n);
            Settings.ImportResult r = read().importConfig(new String(buf.toByteArray(), StandardCharsets.UTF_8));
            show(r.settings);
            mac.setError(null); key.setError(null);
            for (int i = 0; i < Settings.CHARGER_SLOTS; i++) { chargerMac[i].setError(null); chargerKey[i].setError(null); }
            String msg = r.badLines == 0 ? getString(R.string.imported)
                    : getResources().getQuantityString(R.plurals.imported_with_errors, r.badLines, r.badLines);
            Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
        } catch (IOException | SecurityException e) {
            Toast.makeText(this, getString(R.string.import_failed, e.getMessage()), Toast.LENGTH_LONG).show();
        }
    }
}
