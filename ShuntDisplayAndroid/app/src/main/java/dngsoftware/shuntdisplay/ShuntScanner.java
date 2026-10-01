package dngsoftware.shuntdisplay;

import android.Manifest;
import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.LocationManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Listens for Victron Instant Readout advertisements. No pairing or connection is made,
 * so it works alongside VictronConnect and other displays.
 */
public final class ShuntScanner {

    public interface Listener {
        /** An advertisement: {@code data} is the Victron manufacturer data (company ID removed). */
        void onAdvert(String address, String name, byte[] data, int rssi);
        void onScanFailed(int errorCode);
    }

    private final Context ctx;
    private final Handler main = new Handler(Looper.getMainLooper());
    private BluetoothLeScanner scanner;
    private ScanCallback callback;

    public ShuntScanner(Context ctx) { this.ctx = ctx.getApplicationContext(); }

    // ------------------------------------------------------------ permissions and state

    /** Runtime permissions needed to scan on this Android version. */
    public static String[] requiredPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            return new String[]{Manifest.permission.BLUETOOTH_SCAN};
        }
        return new String[]{Manifest.permission.ACCESS_FINE_LOCATION};
    }

    public static boolean hasPermissions(Context ctx) {
        for (String p : requiredPermissions()) {
            if (ctx.checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) return false;
        }
        return true;
    }

    public static BluetoothAdapter adapter(Context ctx) {
        BluetoothManager bm = (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
        return bm == null ? null : bm.getAdapter();
    }

    public static boolean hasBluetooth(Context ctx) {
        return ctx.getPackageManager().hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE) && adapter(ctx) != null;
    }

    public static boolean isBluetoothOn(Context ctx) {
        BluetoothAdapter a = adapter(ctx);
        return a != null && a.isEnabled();
    }

    /** Before Android 12, Bluetooth scans only return results while Location is switched on. */
    public static boolean isLocationOffButNeeded(Context ctx) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) return false;
        LocationManager lm = (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
        if (lm == null) return false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) return !lm.isLocationEnabled();
        return !lm.isProviderEnabled(LocationManager.GPS_PROVIDER)
                && !lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
    }

    // ------------------------------------------------------------ scanning

    /**
     * Starts scanning. With MAC addresses, only those devices are reported (a filtered scan,
     * which Android lets run indefinitely); with null or none, every Victron device is reported.
     */
    @SuppressLint("MissingPermission")
    public boolean start(List<String> macs, Listener listener) {
        stop();
        if (!hasPermissions(ctx) || !isBluetoothOn(ctx)) return false;
        BluetoothAdapter a = adapter(ctx);
        scanner = a == null ? null : a.getBluetoothLeScanner();
        if (scanner == null) return false;

        List<ScanFilter> filters = new ArrayList<>();
        if (macs != null) {
            for (String mac : macs) {
                if (mac != null && !mac.isEmpty())
                    filters.add(new ScanFilter.Builder().setDeviceAddress(mac.toUpperCase(Locale.US)).build());
            }
        }
        if (filters.isEmpty()) {
            filters.add(new ScanFilter.Builder().setManufacturerData(VictronDecoder.VICTRON_COMPANY_ID, new byte[0]).build());
        }

        ScanSettings settings = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
                .setReportDelay(0)
                .build();

        callback = new ScanCallback() {
            @Override public void onScanResult(int callbackType, ScanResult result) { deliver(result, listener); }
            @Override public void onBatchScanResults(List<ScanResult> results) {
                for (ScanResult r : results) deliver(r, listener);
            }
            @Override public void onScanFailed(int errorCode) {
                main.post(() -> listener.onScanFailed(errorCode));
            }
        };
        try {
            scanner.startScan(filters, settings, callback);
            return true;
        } catch (RuntimeException e) {   // SecurityException, IllegalStateException (Bluetooth turning off)
            callback = null;
            return false;
        }
    }

    private void deliver(ScanResult result, Listener listener) {
        ScanRecord rec = result.getScanRecord();
        if (rec == null) return;
        byte[] data = rec.getManufacturerSpecificData(VictronDecoder.VICTRON_COMPANY_ID);
        if (data == null) return;
        String address = result.getDevice().getAddress();
        String name = rec.getDeviceName();
        int rssi = result.getRssi();
        main.post(() -> listener.onAdvert(address, name, data, rssi));
    }

    @SuppressLint("MissingPermission")
    public void stop() {
        if (scanner != null && callback != null) {
            try { scanner.stopScan(callback); } catch (RuntimeException ignored) { }
        }
        callback = null;
        scanner = null;
    }

    public boolean isRunning() { return callback != null; }
}
