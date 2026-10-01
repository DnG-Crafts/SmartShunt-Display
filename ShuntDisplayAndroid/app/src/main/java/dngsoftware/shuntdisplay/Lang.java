package dngsoftware.shuntdisplay;

import android.app.LocaleManager;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Build;
import android.os.LocaleList;

import java.util.Locale;

/**
 * The app's own language, which can differ from the phone's.
 *
 * Android 13+ has per-app languages built in (also in Settings > Apps > Shunt Display >
 * Language), so the choice is stored there. Older versions don't, so the choice is kept in
 * the app's preferences and applied to each screen as it's created ({@link #apply}).
 */
final class Lang {

    private static final String PREFS = "language", KEY = "tag";

    private Lang() { }

    /** The chosen language tag ("de", "zh-TW"...), or "" to follow the phone. */
    static String get(Context ctx) {
        if (Build.VERSION.SDK_INT >= 33) {
            LocaleManager lm = ctx.getSystemService(LocaleManager.class);
            LocaleList l = lm == null ? LocaleList.getEmptyLocaleList() : lm.getApplicationLocales();
            return l.isEmpty() ? "" : l.get(0).toLanguageTag();
        }
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "");
    }

    /**
     * Sets the language. On Android 13+ the system restarts the app's screens itself; on older
     * versions screens pick it up when they're next created (MainActivity recreates itself
     * when it notices the change).
     */
    static void set(Context ctx, String tag) {
        if (tag == null) tag = "";
        if (Build.VERSION.SDK_INT >= 33) {
            LocaleManager lm = ctx.getSystemService(LocaleManager.class);
            if (lm != null) lm.setApplicationLocales(tag.isEmpty()
                    ? LocaleList.getEmptyLocaleList() : LocaleList.forLanguageTags(tag));
            return;
        }
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, tag).apply();
    }

    /**
     * Call from attachBaseContext, after super: applies the chosen language to the screen on
     * Android 12 and older. An override (rather than a wrapped context) survives rotation.
     */
    static void apply(android.app.Activity a, Context base) {
        if (Build.VERSION.SDK_INT >= 33) return;   // the system does it
        String tag = base.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "");
        if (tag.isEmpty()) {   // following the phone again (after a choice earlier in this run)
            Locale.setDefault(android.content.res.Resources.getSystem().getConfiguration().getLocales().get(0));
            return;
        }
        Locale locale = Locale.forLanguageTag(tag);
        Locale.setDefault(locale);
        Configuration override = new Configuration();   // only the locale is set
        override.setLocales(new LocaleList(locale));
        a.applyOverrideConfiguration(override);
    }

    /**
     * Matches a stored tag to one of the picker's tags. Android can report a language
     * slightly differently from how it was set (e.g. "in" for Indonesian, or with a region added).
     */
    static int indexOf(String[] tags, String tag) {
        if (tag == null || tag.isEmpty()) return -1;
        for (int i = 0; i < tags.length; i++) if (tags[i].equalsIgnoreCase(tag)) return i;
        Locale want = Locale.forLanguageTag(tag);
        for (int i = 0; i < tags.length; i++) {
            Locale l = Locale.forLanguageTag(tags[i]);
            if (!l.getLanguage().equals(want.getLanguage())) continue;
            // Chinese: tell Simplified and Traditional apart by region or script
            if (l.getLanguage().equals("zh")) {
                boolean wantHant = "Hant".equals(want.getScript()) || "TW".equals(want.getCountry())
                        || "HK".equals(want.getCountry()) || "MO".equals(want.getCountry());
                if (wantHant != "TW".equals(l.getCountry())) continue;
            }
            return i;
        }
        return -1;
    }
}
