package dngsoftware.shuntdisplay;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.content.res.Configuration;
import android.os.Build;
import android.view.View;
import android.view.WindowInsets;

/** Theme, orientation and window-inset helpers shared by the activities. */
final class Ui {
    private Ui() {}

    /** Call before super.onCreate(): picks the dark or light theme. */
    static void applyTheme(Activity a, Settings s) {
        a.setTheme(isDark(a, s) ? R.style.Theme_ShuntDisplay_Dark : R.style.Theme_ShuntDisplay_Light);
    }

    static boolean isDark(Activity a, Settings s) {
        if (s.theme == Settings.THEME_DARK) return true;
        if (s.theme == Settings.THEME_LIGHT) return false;
        int night = a.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return night == Configuration.UI_MODE_NIGHT_YES;
    }

    static void applyOrientation(Activity a, Settings s) {
        int o;
        if (s.orientation == Settings.ORIENT_PORTRAIT) o = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT;
        else if (s.orientation == Settings.ORIENT_LANDSCAPE) o = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE;
        else if (s.orientation == Settings.ORIENT_LANDSCAPE_FLIPPED) o = ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE;
        else o = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED;
        a.setRequestedOrientation(o);
    }

    /** Draws behind the system bars on every Android version (it's forced from Android 15). */
    @SuppressWarnings("deprecation")
    static void edgeToEdge(Activity a) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            a.getWindow().setDecorFitsSystemWindows(false);
        } else {
            View decor = a.getWindow().getDecorView();
            decor.setSystemUiVisibility(decor.getSystemUiVisibility()
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    /**
     * Full screen: hides the status and navigation bars (a swipe from the edge shows them
     * briefly) and lets the background extend behind a notch or camera cut-out.
     */
    @SuppressWarnings("deprecation")
    static void setFullScreen(Activity a, boolean on) {
        android.view.Window w = a.getWindow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            android.view.WindowManager.LayoutParams lp = w.getAttributes();
            lp.layoutInDisplayCutoutMode = on
                    ? android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
                    : android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_DEFAULT;
            w.setAttributes(lp);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            android.view.WindowInsetsController c = w.getInsetsController();
            if (c == null) return;
            if (on) {
                c.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                c.hide(WindowInsets.Type.systemBars());
            } else {
                c.show(WindowInsets.Type.systemBars());
            }
        } else {
            View decor = w.getDecorView();
            int keep = decor.getSystemUiVisibility() & (View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                    | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
            int flags = keep | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;
            if (on) flags |= View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY;
            decor.setSystemUiVisibility(flags);
        }
    }

    /** Pads {@code v} so its content stays clear of the status/navigation bars and display cut-outs. */
    @SuppressWarnings("deprecation")
    static void padForSystemBars(View v) {
        final int l = v.getPaddingLeft(), t = v.getPaddingTop(), r = v.getPaddingRight(), b = v.getPaddingBottom();
        v.setOnApplyWindowInsetsListener((view, insets) -> {
            int il, it, ir, ib;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                android.graphics.Insets in = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                il = in.left; it = in.top; ir = in.right; ib = in.bottom;
            } else {
                il = insets.getSystemWindowInsetLeft(); it = insets.getSystemWindowInsetTop();
                ir = insets.getSystemWindowInsetRight(); ib = insets.getSystemWindowInsetBottom();
                // Android 9-10: keep content clear of a notch as well
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && insets.getDisplayCutout() != null) {
                    android.view.DisplayCutout dc = insets.getDisplayCutout();
                    il = Math.max(il, dc.getSafeInsetLeft()); it = Math.max(it, dc.getSafeInsetTop());
                    ir = Math.max(ir, dc.getSafeInsetRight()); ib = Math.max(ib, dc.getSafeInsetBottom());
                }
            }
            view.setPadding(l + il, t + it, r + ir, b + ib);
            return insets;
        });
        v.requestApplyInsets();
    }

    /**
     * Keeps a view's content at most {@code maxDp} wide by adding equal padding on both sides,
     * so forms and lists don't stretch across a landscape tablet. Phones are unaffected.
     */
    static void limitContentWidth(View v, int maxDp) {
        final int max = Math.round(maxDp * v.getResources().getDisplayMetrics().density);
        final int[] base = {-1, -1};   // the view's own left/right padding, read once it's resolved
        v.addOnLayoutChangeListener((view, l, t, r, b, ol, ot, or, ob) -> {
            if (base[0] < 0) { base[0] = view.getPaddingLeft(); base[1] = view.getPaddingRight(); }
            int extra = Math.max(0, (r - l - base[0] - base[1] - max) / 2);
            int left = base[0] + extra, right = base[1] + extra;
            if (view.getPaddingLeft() != left || view.getPaddingRight() != right)
                view.post(() -> view.setPadding(left, view.getPaddingTop(), right, view.getPaddingBottom()));
        });
    }
}
