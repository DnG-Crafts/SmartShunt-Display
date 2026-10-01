package dngsoftware.shuntdisplay;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.ListView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Lists Victron battery monitors in range (or, with {@link #EXTRA_CHARGERS}, Victron chargers);
 * tapping one returns its MAC address.
 */
public class DeviceScanActivity extends Activity implements ShuntScanner.Listener {

    public static final String EXTRA_MAC = "mac";
    public static final String EXTRA_CHARGERS = "chargers";
    private boolean chargers;
    private static final int REQ_PERMISSIONS = 1;

    private static final class Found {
        String address, name, model;
        int rssi, modelId;
        long seen;
    }

    private final Map<String, Found> found = new HashMap<>();
    private int otherVictron = 0;
    private final List<String> otherAddresses = new ArrayList<>();
    private ShuntScanner scanner;
    private ArrayAdapter<Found> adapter;
    private TextView status;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override protected void attachBaseContext(android.content.Context base) { super.attachBaseContext(base); Lang.apply(this, base); }

    @Override protected void onCreate(Bundle saved) {
        Ui.applyTheme(this, Settings.load(this));
        super.onCreate(saved);
        Ui.edgeToEdge(this);
        setContentView(R.layout.activity_devices);
        Ui.padForSystemBars(findViewById(R.id.root));
        status = findViewById(R.id.status);
        findViewById(R.id.close).setOnClickListener(v -> finish());
        scanner = new ShuntScanner(this);
        chargers = getIntent().getBooleanExtra(EXTRA_CHARGERS, false);
        if (chargers) {
            ((TextView) findViewById(R.id.title)).setText(R.string.nearby_chargers_title);
            ((TextView) findViewById(R.id.empty)).setText(R.string.nearby_chargers_empty);
        }

        adapter = new ArrayAdapter<Found>(this, 0) {
            @Override public View getView(int pos, View v, ViewGroup parent) {
                if (v == null) v = LayoutInflater.from(getContext()).inflate(R.layout.item_device, parent, false);
                Found f = getItem(pos);
                String title = f.model != null ? f.model : (f.name != null ? f.name : getString(R.string.victron_device));
                ((TextView) v.findViewById(R.id.title)).setText(title);
                String sub = f.address.toLowerCase(Locale.US) + "   " + f.rssi + " dBm";
                if (f.name != null && f.model != null) sub = f.name + "   " + sub;
                ((TextView) v.findViewById(R.id.subtitle)).setText(sub);
                return v;
            }
        };
        ListView list = findViewById(R.id.list);
        Ui.limitContentWidth(list, 720);
        Ui.limitContentWidth(status, 720);
        list.setAdapter(adapter);
        list.setEmptyView(findViewById(R.id.empty));
        list.setOnItemClickListener((p, v, pos, id) -> {
            Found f = adapter.getItem(pos);
            setResult(RESULT_OK, new Intent().putExtra(EXTRA_MAC, Settings.normaliseMac(f.address)));
            finish();
        });
    }

    @Override protected void onStart() {
        super.onStart();
        startScan();
        handler.post(refresh);
    }

    @Override protected void onStop() {
        super.onStop();
        scanner.stop();
        handler.removeCallbacks(refresh);
    }

    private void startScan() {
        if (!ShuntScanner.hasPermissions(this)) {
            requestPermissions(ShuntScanner.requiredPermissions(), REQ_PERMISSIONS);
            return;
        }
        scanner.start(null, this);   // every Victron device
    }

    @Override public void onRequestPermissionsResult(int req, String[] perms, int[] results) {
        super.onRequestPermissionsResult(req, perms, results);
        if (req == REQ_PERMISSIONS && ShuntScanner.hasPermissions(this)) startScan();
    }

    @Override public void onAdvert(String address, String name, byte[] data, int rssi) {
        int kind = VictronDecoder.chargerKind(VictronDecoder.recordType(data));
        if (chargers ? kind < 0 : !VictronDecoder.isBatteryMonitor(data)) {
            if (!otherAddresses.contains(address)) { otherAddresses.add(address); otherVictron++; }
            return;
        }
        Found f = found.get(address);
        if (f == null) { f = new Found(); f.address = address; found.put(address, f); }
        f.rssi = rssi;
        if (name != null) f.name = name;
        f.modelId = VictronDecoder.modelId(data);
        f.model = !chargers ? VictronDecoder.modelName(f.modelId)
                : getString(kind == ChargerReading.KIND_SOLAR ? R.string.charger_solar
                            : kind == ChargerReading.KIND_DCDC ? R.string.charger_dcdc : R.string.charger_ac);
        f.seen = SystemClock.elapsedRealtime();
    }

    @Override public void onScanFailed(int errorCode) {
        status.setText(getString(R.string.scan_failed, errorCode));
    }

    /** Refreshes the list twice a second, strongest signal first. */
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            long now = SystemClock.elapsedRealtime();
            List<Found> items = new ArrayList<>();
            for (Found f : found.values()) if (now - f.seen < 30_000) items.add(f);
            Collections.sort(items, (a, b) -> Integer.compare(b.rssi, a.rssi));
            adapter.clear();
            adapter.addAll(items);
            if (!ShuntScanner.hasPermissions(DeviceScanActivity.this)) status.setText(R.string.need_permission);
            else if (!ShuntScanner.isBluetoothOn(DeviceScanActivity.this)) status.setText(R.string.bluetooth_off);
            else if (ShuntScanner.isLocationOffButNeeded(DeviceScanActivity.this)) status.setText(R.string.location_off);
            else if (chargers) status.setText(R.string.scanning_chargers);
            else if (otherVictron > 0) status.setText(getResources().getQuantityString(
                    R.plurals.scanning_others, otherVictron, otherVictron));
            else status.setText(R.string.scanning);
            if (!scanner.isRunning() && ShuntScanner.hasPermissions(DeviceScanActivity.this)
                    && ShuntScanner.isBluetoothOn(DeviceScanActivity.this)) startScan();
            handler.postDelayed(this, 500);
        }
    };
}
