package dngsoftware.shuntdisplay;

import android.content.Context;
import android.content.res.TypedArray;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.View;

/**
 * The dashboard, in the same design as the AlphaESS display: a live energy-flow picture (the
 * charge sources, the battery and the loads around a hub, with dots running along the lines the way the
 * energy flows), a state-of-charge card and a card of the shunt's readings. Landscape puts the
 * flow picture on the left and the cards on the right; portrait stacks them. Same design as the
 * Raspberry Pi version.
 *
 * The nodes (which, where, what they say) are worked out by MainActivity; see its flowNodes().
 */
public class DashboardView extends View {

    /** Colour roles; resolved from the current theme. */
    public static final int TEXT = 0, MUTED = 1, GOOD = 2, WARN = 3, BAD = 4;
    /** Node icons. */
    public static final int CHARGER = 0, BATTERY = 1, LOADS = 2, I_SOLAR = 3, I_CAR = 4, I_CARAVAN = 5, I_BOAT = 6;
    /** Where a node sits around the hub. */
    public static final int TOP = 0, LEFT = 1, RIGHT = 2, BOTTOM = 3;
    /** Icon colours. */
    public static final int C_CHARGER = 0, C_BATTERY = 1, C_LOADS = 2, C_ACCENT = 3;
    /** Icons in the readings card. */
    public static final int I_VOLT = 10, I_AMP = 11, I_POWER = 12, I_CONSUMED = 13, I_STARTER = 14,
            I_MIDPOINT = 15, I_TEMP = 16, I_SIGNAL = 17;

    /** Below this many watts the battery counts as idle (no flow shown). */
    public static final float IDLE_W = 3;

    /** One circle in the flow picture. */
    public static final class Node {
        public final int place, color, icon;     // TOP…, C_…, CHARGER…
        public final String value, label, extra;
        public final int extraColor;             // colour role
        public final float flow;                 // signed watts on its line, + toward the hub
        public Node(int place, int color, int icon, String value, String label, float flow, String extra, int extraColor) {
            this.place = place; this.color = color; this.icon = icon; this.value = value; this.label = label;
            this.flow = flow; this.extra = extra == null ? "" : extra; this.extraColor = extraColor;
        }
        boolean active() { return !Float.isNaN(flow) && Math.abs(flow) > IDLE_W; }
    }

    /** What to show. Strings are ready to draw; colours are roles above. */
    public static final class State {
        public String title = "SmartShunt";
        public String soc = "--", time = "--";
        public String timeLabel = "", status = "", detail = "";
        public int socColor = MUTED, statusColor = WARN;
        public float barPercent = -1;           // < 0 = empty bar
        public boolean stale = true;
        public Node[] nodes = new Node[0];
        public float level = -1;                 // battery icon fill, %
        public final int[] readIcon = new int[6], readIconColor = new int[6], readValueColor = new int[6];
        public final String[] readLabel = {"", "", "", "", "", ""}, readValue = {"--", "--", "--", "--", "--", "--"};
        /** For TalkBack. */
        public String voltage = "--", current = "--";
    }

    public interface Listener {
        void onCogTapped();
        void onStatusTapped();
    }

    private State state = new State();
    private Listener listener;

    private final int[] colors = new int[5];
    private final int[] source = new int[4];
    private int bg, panel, track, line;
    private final float dp;
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint label = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint value = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final RectF r = new RectF();

    private final RectF cogHit = new RectF(), statusHit = new RectF();
    private boolean cogPressed;
    private final String lSoc, lReadings;
    private float u;                           // layout unit: 1/400 of the shorter side
    private final Runnable frame = this::invalidate;

    public DashboardView(Context ctx) { this(ctx, null); }

    public DashboardView(Context ctx, AttributeSet attrs) {
        super(ctx, attrs);
        dp = getResources().getDisplayMetrics().density;
        TypedArray a = ctx.getTheme().obtainStyledAttributes(new int[]{
                R.attr.colorBg, R.attr.colorPanel, R.attr.colorTrack, R.attr.colorText,
                R.attr.colorMuted, R.attr.colorGood, R.attr.colorWarn, R.attr.colorBad, R.attr.colorLine,
                R.attr.colorCharger, R.attr.colorBattery, R.attr.colorLoads, R.attr.colorFlowAccent});
        bg = a.getColor(0, Color.BLACK);
        panel = a.getColor(1, Color.DKGRAY);
        track = a.getColor(2, Color.BLACK);
        colors[TEXT] = a.getColor(3, Color.WHITE);
        colors[MUTED] = a.getColor(4, Color.GRAY);
        colors[GOOD] = a.getColor(5, Color.GREEN);
        colors[WARN] = a.getColor(6, Color.YELLOW);
        colors[BAD] = a.getColor(7, Color.RED);
        line = a.getColor(8, Color.DKGRAY);
        source[C_CHARGER] = a.getColor(9, Color.YELLOW);
        source[C_BATTERY] = a.getColor(10, Color.GREEN);
        source[C_LOADS] = a.getColor(11, Color.BLUE);
        source[C_ACCENT] = a.getColor(12, Color.MAGENTA);
        a.recycle();
        lSoc = ctx.getString(R.string.dash_soc);
        lReadings = ctx.getString(R.string.dash_readings);
        label.setTypeface(Typeface.DEFAULT);
        value.setTypeface(Typeface.DEFAULT_BOLD);
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeCap(Paint.Cap.ROUND);
        setClickable(true);
    }

    @Override protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        removeCallbacks(frame);
    }

    public void setListener(Listener l) { listener = l; }

    public void setState(State s) {
        state = s;
        setContentDescription(getContext().getString(R.string.dashboard_description, s.soc, s.voltage, s.current, s.status));
        invalidate();
    }

    // ------------------------------------------------------------ helpers

    /** Colour a blended toward b by t (0 = a, 1 = b). */
    private static int mix(int a, int b, float t) {
        return Color.rgb(Math.round(Color.red(a) + (Color.red(b) - Color.red(a)) * t),
                Math.round(Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                Math.round(Color.blue(a) + (Color.blue(b) - Color.blue(a)) * t));
    }

    /** Sets the paint's text size to at most {@code maxSize}, shrinking until it fits {@code maxW}. */
    private static float fit(Paint p, String s, float maxW, float maxSize) {
        p.setTextSize(maxSize);
        float w = p.measureText(s);
        if (w > maxW && w > 0) p.setTextSize(maxSize * maxW / w);
        return p.getTextSize();
    }

    private void text(Canvas c, String s, float x, float baseline, Paint p, float size, int col, Paint.Align align) {
        p.setTextSize(size);
        p.setColor(col);
        p.setTextAlign(align);
        c.drawText(s, x, baseline, p);
        p.setTextAlign(Paint.Align.LEFT);
    }

    private float ascent(Paint p, float size) { p.setTextSize(size); return -p.ascent(); }

    private void circle(Canvas c, float x, float y, float rad, int col) {
        fill.setColor(col);
        c.drawCircle(x, y, rad, fill);
    }

    private void line(Canvas c, float x1, float y1, float x2, float y2, float w, int col) {
        stroke.setStrokeWidth(w);
        stroke.setColor(col);
        c.drawLine(x1, y1, x2, y2, stroke);
    }

    private void rrect(Canvas c, float x, float y, float w, float h, float rad, int col) {
        fill.setColor(col);
        r.set(x, y, x + w, y + h);
        c.drawRoundRect(r, rad, rad, fill);
    }

    /** A lightning bolt, h tall, filled. */
    private void bolt(Canvas c, float cx, float cy, float h, int col) {
        path.reset();
        path.moveTo(cx + h * 0.1f, cy - h * 0.5f);
        path.lineTo(cx - h * 0.3f, cy + h * 0.06f);
        path.lineTo(cx - h * 0.02f, cy + h * 0.06f);
        path.lineTo(cx - h * 0.1f, cy + h * 0.5f);
        path.lineTo(cx + h * 0.3f, cy - h * 0.06f);
        path.lineTo(cx + h * 0.02f, cy - h * 0.06f);
        path.close();
        fill.setColor(col);
        c.drawPath(path, fill);
    }

    private void triangle(Canvas c, float x1, float y1, float x2, float y2, float x3, float y3, int col) {
        path.reset();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        path.lineTo(x3, y3);
        path.close();
        fill.setColor(col);
        c.drawPath(path, fill);
    }

    /** Line icons, {@code s} across (the same drawings as the Raspberry Pi version). */
    private void icon(Canvas c, int kind, float cx, float cy, float s, int col, int bgCol, float level) {
        float w = Math.max(2, s * 0.09f);
        switch (kind) {
            case CHARGER:                                            // a mains plug
                line(c, cx - s * 0.15f, cy - s * 0.46f, cx - s * 0.15f, cy - s * 0.24f, w, col);
                line(c, cx + s * 0.15f, cy - s * 0.46f, cx + s * 0.15f, cy - s * 0.24f, w, col);
                rrect(c, cx - s * 0.3f, cy - s * 0.26f, s * 0.6f, s * 0.36f, s * 0.1f, col);
                bolt(c, cx, cy - s * 0.08f, s * 0.28f, bgCol);
                rrect(c, cx - s * 0.08f, cy + s * 0.08f, s * 0.16f, s * 0.16f, s * 0.03f, col);
                line(c, cx, cy + s * 0.22f, cx, cy + s * 0.46f, w, col);
                break;
            case I_SOLAR:                                            // a sun
                circle(c, cx, cy, s * 0.2f, col);
                for (int i = 0; i < 8; i++) {
                    double a = i * Math.PI / 4;
                    float co = (float) Math.cos(a), si = (float) Math.sin(a);
                    line(c, cx + co * s * 0.32f, cy + si * s * 0.32f, cx + co * s * 0.46f, cy + si * s * 0.46f, w, col);
                }
                break;
            case I_CAR: {                                            // a car: DC-DC charger or alternator
                path.reset();
                path.moveTo(cx - s * 0.3f, cy - s * 0.04f);
                path.lineTo(cx - s * 0.19f, cy - s * 0.34f);
                path.lineTo(cx + s * 0.19f, cy - s * 0.34f);
                path.lineTo(cx + s * 0.32f, cy - s * 0.04f);
                path.close();
                fill.setColor(col);
                c.drawPath(path, fill);
                for (int sx = -1; sx <= 1; sx += 2) {                // side windows
                    path.reset();
                    path.moveTo(cx + sx * s * 0.03f, cy - s * 0.08f);
                    path.lineTo(cx + sx * s * 0.03f, cy - s * 0.27f);
                    path.lineTo(cx + sx * s * 0.14f, cy - s * 0.27f);
                    path.lineTo(cx + sx * s * 0.22f, cy - s * 0.08f);
                    path.close();
                    fill.setColor(bgCol);
                    c.drawPath(path, fill);
                }
                rrect(c, cx - s * 0.47f, cy - s * 0.08f, s * 0.94f, s * 0.3f, s * 0.1f, col);
                for (int sx = -1; sx <= 1; sx += 2) {
                    circle(c, cx + sx * s * 0.25f, cy + s * 0.24f, s * 0.16f, bgCol);
                    circle(c, cx + sx * s * 0.25f, cy + s * 0.24f, s * 0.12f, col);
                    circle(c, cx + sx * s * 0.25f, cy + s * 0.24f, s * 0.05f, bgCol);
                }
                break;
            }
            case I_CARAVAN: {                                        // a caravan: body, window, door, wheel, drawbar
                float l = cx - s * 0.5f, rt = cx + s * 0.32f, t = cy - s * 0.38f, b = cy + s * 0.22f;
                rrect(c, l, t, rt - l, b - t, s * 0.16f, col);
                rrect(c, l + w, t + w, rt - l - 2 * w, b - t - 2 * w, s * 0.11f, bgCol);
                rrect(c, l + s * 0.11f, t + s * 0.13f, s * 0.32f, s * 0.17f, s * 0.03f, col);
                rrect(c, cx + s * 0.05f, t + s * 0.13f, s * 0.15f, b - t - s * 0.13f, s * 0.03f, col);
                line(c, rt, b - s * 0.07f, cx + s * 0.5f, b - s * 0.07f, w, col);
                circle(c, cx - s * 0.15f, b + s * 0.07f, s * 0.17f, bgCol);
                circle(c, cx - s * 0.15f, b + s * 0.07f, s * 0.125f, col);
                circle(c, cx - s * 0.15f, b + s * 0.07f, s * 0.05f, bgCol);
                break;
            }
            case I_BOAT:                                             // a sailing boat: hull and two sails
                path.reset();
                path.moveTo(cx - s * 0.48f, cy + s * 0.14f);
                path.lineTo(cx + s * 0.48f, cy + s * 0.14f);
                path.lineTo(cx + s * 0.32f, cy + s * 0.4f);
                path.lineTo(cx - s * 0.32f, cy + s * 0.4f);
                path.close();
                fill.setColor(col);
                c.drawPath(path, fill);
                line(c, cx - s * 0.02f, cy - s * 0.48f, cx - s * 0.02f, cy + s * 0.14f, w * 0.8f, col);
                triangle(c, cx - s * 0.08f, cy - s * 0.42f, cx - s * 0.08f, cy + s * 0.06f, cx - s * 0.4f, cy + s * 0.06f, col);
                triangle(c, cx + s * 0.04f, cy - s * 0.34f, cx + s * 0.04f, cy + s * 0.06f, cx + s * 0.34f, cy + s * 0.06f, col);
                break;
            case LOADS: {                                            // a house
                float l = cx - s * 0.36f, rt = cx + s * 0.36f, t = cy - s * 0.44f, b = cy + s * 0.4f, eave = cy - s * 0.08f;
                line(c, cx - s * 0.48f, eave + s * 0.06f, cx, t, w, col);
                line(c, cx, t, cx + s * 0.48f, eave + s * 0.06f, w, col);
                line(c, l, eave, l, b, w, col);
                line(c, rt, eave, rt, b, w, col);
                line(c, l, b, rt, b, w, col);
                rrect(c, cx - s * 0.1f, cy + s * 0.1f, s * 0.2f, s * 0.3f, s * 0.03f, col);
                break;
            }
            case BATTERY:
            case I_MIDPOINT:
            case I_CONSUMED: {
                float bw = s * 0.5f, bh = s * 0.8f, x = cx - bw / 2, y = cy - bh / 2 + s * 0.05f;
                rrect(c, cx - s * 0.1f, y - s * 0.1f, s * 0.2f, s * 0.12f, s * 0.03f, col);
                rrect(c, x, y, bw, bh, s * 0.08f, col);
                rrect(c, x + w, y + w, bw - 2 * w, bh - 2 * w, s * 0.05f, bgCol);
                if (kind == I_MIDPOINT) {
                    line(c, x + 2 * w, y + bh / 2, x + bw - 2 * w, y + bh / 2, w, col);
                } else {
                    if (kind == I_CONSUMED) level = 50;
                    if (level > 0) {
                        float fh = (bh - 4 * w) * Math.min(100, level) / 100;
                        rrect(c, x + 2 * w, y + bh - 2 * w - fh, bw - 4 * w, fh, s * 0.03f, col);
                    }
                }
                if (kind == I_CONSUMED) badge(c, cx + s * 0.32f, cy + s * 0.3f, s * 0.22f, col, bgCol, false);
                break;
            }
            case I_STARTER: {                                        // a car battery: wide, two terminals
                float bw = s * 0.84f, bh = s * 0.54f, x = cx - bw / 2, y = cy - bh / 2 + s * 0.08f;
                rrect(c, x + bw * 0.22f - s * 0.08f, y - s * 0.12f, s * 0.16f, s * 0.14f, s * 0.03f, col);
                rrect(c, x + bw * 0.78f - s * 0.08f, y - s * 0.12f, s * 0.16f, s * 0.14f, s * 0.03f, col);
                rrect(c, x, y, bw, bh, s * 0.08f, col);
                rrect(c, x + w, y + w, bw - 2 * w, bh - 2 * w, s * 0.05f, bgCol);
                line(c, x + bw * 0.14f, y + bh * 0.45f, x + bw * 0.3f, y + bh * 0.45f, w * 0.8f, col);
                line(c, x + bw * 0.62f, y + bh * 0.45f, x + bw * 0.86f, y + bh * 0.45f, w * 0.8f, col);
                line(c, x + bw * 0.74f, y + bh * 0.3f, x + bw * 0.74f, y + bh * 0.6f, w * 0.8f, col);
                break;
            }
            case I_VOLT:
                bolt(c, cx, cy, s * 0.95f, col);
                break;
            case I_AMP:                                              // arrows both ways
                for (int d = 1; d >= -1; d -= 2) {
                    float yy = cy - s * 0.17f * d, tip = cx + s * 0.44f * d;
                    line(c, cx - s * 0.4f, yy, cx + s * 0.4f, yy, w, col);
                    triangle(c, tip, yy, tip - s * 0.2f * d, yy - s * 0.14f, tip - s * 0.2f * d, yy + s * 0.14f, col);
                }
                break;
            case I_POWER:                                            // a bolt in a ring
                stroke.setStrokeWidth(w);
                stroke.setColor(col);
                c.drawCircle(cx, cy, s * 0.46f - w / 2, stroke);
                bolt(c, cx, cy, s * 0.56f, col);
                break;
            case I_TEMP:                                             // a thermometer
                circle(c, cx, cy + s * 0.28f, s * 0.17f, col);
                rrect(c, cx - s * 0.1f, cy - s * 0.46f, s * 0.2f, s * 0.7f, s * 0.1f, col);
                rrect(c, cx - s * 0.1f + w, cy - s * 0.46f + w, s * 0.2f - 2 * w, s * 0.5f, s * 0.06f, bgCol);
                break;
            default:                                                 // I_SIGNAL: four bars
                for (int i = 0; i < 4; i++) {
                    float h = s * (0.25f + 0.2f * i), bw = s * 0.16f;
                    rrect(c, cx - s * 0.44f + i * s * 0.24f, cy + s * 0.4f - h, bw, h, bw * 0.3f, col);
                }
        }
    }

    /** A small round - or + badge. */
    private void badge(Canvas c, float cx, float cy, float rad, int col, int bgCol, boolean plus) {
        circle(c, cx, cy, rad + Math.max(1.5f, rad * 0.3f), bgCol);
        circle(c, cx, cy, rad, col);
        float w = Math.max(1.5f, rad * 0.32f);
        fill.setColor(bgCol);
        c.drawRect(cx - rad * 0.55f, cy - w / 2, cx + rad * 0.55f, cy + w / 2, fill);
        if (plus) c.drawRect(cx - w / 2, cy - rad * 0.55f, cx + w / 2, cy + rad * 0.55f, fill);
    }

    private void cog(Canvas c, float cx, float cy, float rad, int col, int hole) {
        for (int i = 0; i < 8; i++) {
            double a = i * Math.PI / 4;
            circle(c, cx + (float) Math.cos(a) * rad * 1.2f, cy + (float) Math.sin(a) * rad * 1.2f, rad * 0.29f, col);
        }
        circle(c, cx, cy, rad, col);
        circle(c, cx, cy, rad * 0.42f, hole);
    }

    // ------------------------------------------------------------ drawing

    @Override protected void onDraw(Canvas c) {
        float pl = getPaddingLeft(), pt = getPaddingTop();
        float W = getWidth() - pl - getPaddingRight(), H = getHeight() - pt - getPaddingBottom();
        u = Math.max(0.8f * dp, Math.min(W, H) / 400f);
        c.drawColor(bg);
        c.save();
        c.translate(pl, pt);
        float m = 10 * u, g = 10 * u;
        float top = header(c, W, m, pl, pt);
        float[] flow, batt, info;
        if (W >= H * 1.15f) {                                          // landscape
            float fw = (W - 2 * m - g) * 0.56f, rx = m + fw + g, rw = W - 2 * m - fw - g;
            float bh = (H - top - m - g) * 0.36f;
            flow = new float[]{m, top, fw, H - top - m};
            batt = new float[]{rx, top, rw, bh};
            info = new float[]{rx, top + bh + g, rw, H - top - m - bh - g};
        } else {                                                       // portrait
            float avail = H - top - m - 2 * g, fh = avail * 0.5f, bh = avail * 0.19f;
            flow = new float[]{m, top, W - 2 * m, fh};
            batt = new float[]{m, top + fh + g, W - 2 * m, bh};
            info = new float[]{m, top + fh + bh + 2 * g, W - 2 * m, avail - fh - bh};
        }
        for (float[] k : new float[][]{flow, batt, info}) rrect(c, k[0], k[1], k[2], k[3], 16 * u, panel);
        float now = SystemClock.uptimeMillis() / 1000f;
        boolean moving = flow(c, flow, now);
        battery(c, batt);
        readings(c, info);
        c.restore();
        removeCallbacks(frame);                        // one pending frame at a time, however often we're redrawn
        if (moving) postOnAnimationDelayed(frame, 33); // about 30 frames a second while energy flows
    }

    /** Title, status pill and cog. Returns the top of the cards. */
    private float header(Canvas c, float W, float m, float pl, float pt) {
        State st = state;
        float hh = 44 * u, mid = m + hh / 2, ts = 22 * u;
        float cr = 9 * u, cx = W - m - cr * 1.6f;
        cog(c, cx, mid, cr, cogPressed ? colors[TEXT] : colors[MUTED], bg);
        float ws = 15 * u, ds = 13 * u;
        value.setTextSize(ws);
        float wWord = value.measureText(st.status);
        label.setTextSize(ds);
        float wDet = st.detail.isEmpty() ? 0 : label.measureText(st.detail);
        float pad = 12 * u, dot = 4 * u, ph = 30 * u;
        float pw = pad + dot * 2 + 8 * u + wWord + (wDet > 0 ? 10 * u + wDet : 0) + pad;
        float px = cx - cr * 2.4f - pw;
        rrect(c, px, mid - ph / 2, pw, ph, ph / 2, panel);
        float x = px + pad;
        circle(c, x + dot, mid, dot, colors[st.statusColor]);
        x += dot * 2 + 8 * u;
        float base = mid + ascent(value, ws) * 0.36f;
        text(c, st.status, x, base, value, ws, colors[st.statusColor], Paint.Align.LEFT);
        if (wDet > 0) text(c, st.detail, x + wWord + 10 * u, base, label, ds, colors[MUTED], Paint.Align.LEFT);
        // title, in the space left of the pill
        float tsz = fit(value, st.title, px - m - 16 * u, ts);
        text(c, st.title, m + 4 * u, mid + ascent(value, tsz) * 0.36f, value, tsz, colors[TEXT], Paint.Align.LEFT);
        float hs = Math.max(48 * dp, cr * 4);
        cogHit.set(pl + W - m - hs, pt + mid - hs / 2, pl + W, pt + mid + hs / 2);
        statusHit.set(pl + px, pt + mid - Math.max(ph, 44 * dp) / 2, pl + px + pw, pt + mid + Math.max(ph, 44 * dp) / 2);
        return m + hh + 4 * u;
    }

    // ------------------------------------------------------------ energy flow

    /** Draws the flow picture; returns true while dots are moving. */
    private boolean flow(Canvas c, float[] rect, float now) {
        State st = state;
        float x = rect[0], y = rect[1], w = rect[2], h = rect[3];
        boolean hasLeft = false;
        for (Node n : st.nodes) if (n.place == LEFT) hasLeft = true;
        // With nothing on the left (no extra charger), the upright sits a little left of centre.
        float pad = 14 * u, R = Math.min(w, h) * 0.105f, cx = x + w * (hasLeft ? 0.5f : 0.44f), cy = y + h / 2, hub = R * 0.42f;
        float[][] pos = {{cx, y + pad + R}, {x + pad + R + 6 * u, cy}, {x + w - pad - R - 6 * u, cy}, {cx, y + h - pad - R}};
        boolean moving = false;

        // lines, then the moving dots
        for (Node n : st.nodes) {
            float nx = pos[n.place][0], ny = pos[n.place][1];
            int col = source[n.color];
            float dx = cx - nx, dy = cy - ny, d = (float) Math.hypot(dx, dy), ux = dx / d, uy = dy / d;
            float ax = nx + ux * (R + 6 * u), ay = ny + uy * (R + 6 * u);
            float bx = cx - ux * (hub + 6 * u), by = cy - uy * (hub + 6 * u);
            boolean on = !st.stale && n.active();
            line(c, ax, ay, bx, by, 4 * u, on ? mix(col, panel, 0.72f) : line);
            if (!on) continue;
            moving = true;
            float length = (float) Math.hypot(bx - ax, by - ay);
            boolean forward = n.flow > 0;                            // toward the hub
            float speed = (26 + 22 * Math.min(3f, Math.abs(n.flow) / 1000)) * u, gap = 20 * u;
            for (float dd = (now * speed) % gap; dd < length; dd += gap) {
                float t = forward ? dd : length - dd;
                float edge = Math.min(dd, length - dd) / (6 * u);      // fade in and out at the ends
                circle(c, ax + ux * t, ay + uy * t, 3.2f * u * Math.min(1f, 0.35f + edge * 0.65f), col);
            }
        }

        // hub
        circle(c, cx, cy, hub + 2 * u, line);
        circle(c, cx, cy, hub, panel);
        bolt(c, cx, cy, hub * 1.24f, colors[MUTED]);

        // nodes and their labels
        float vs = 20 * u, ls = 13 * u;
        for (Node n : st.nodes) {
            float nx = pos[n.place][0], ny = pos[n.place][1];
            int col = source[n.color];
            boolean on = !st.stale && n.active();
            int tint = mix(col, panel, 0.86f);
            circle(c, nx, ny, R, tint);
            stroke.setStrokeWidth(3 * u);
            stroke.setColor(on ? col : mix(col, panel, 0.55f));
            c.drawCircle(nx, ny, R - 1.5f * u, stroke);
            icon(c, n.icon, nx, ny, R * 1.05f, col, tint, n.icon == BATTERY ? st.level : -1);
            int vcol = st.stale || "--".equals(n.value) ? colors[MUTED] : colors[TEXT];
            int ecol = colors[n.extraColor];
            if (n.place == TOP || n.place == BOTTOM) {                  // beside: top on the right, bottom on the left
                boolean right = n.place == TOP;
                float lx = right ? nx + R + 12 * u : nx - R - 12 * u;
                float maxw = right ? x + w - pad - lx : lx - x - pad;
                Paint.Align al = right ? Paint.Align.LEFT : Paint.Align.RIGHT;
                text(c, n.value, lx, ny + vs * 0.1f, value, fit(value, n.value, maxw, vs), vcol, al);
                text(c, n.label, lx, ny + vs * 0.1f + ls * 1.5f, label, fit(label, n.label, maxw, ls), colors[MUTED], al);
                if (!n.extra.isEmpty())
                    text(c, n.extra, lx, ny + vs * 0.1f + ls * 2.85f, label, fit(label, n.extra, maxw, ls * 0.92f), ecol, al);
            } else if (n.place == LEFT) {                               // above, clear of the battery's labels
                float maxw = Math.min(2 * (nx - x - 4 * u), R * 3.2f);
                float bottom = ny - R - 10 * u, lb = bottom - (n.extra.isEmpty() ? 0 : ls * 1.3f);
                if (!n.extra.isEmpty())
                    text(c, n.extra, nx, bottom, label, fit(label, n.extra, maxw, ls * 0.92f), ecol, Paint.Align.CENTER);
                text(c, n.label, nx, lb, label, fit(label, n.label, maxw, ls), colors[MUTED], Paint.Align.CENTER);
                text(c, n.value, nx, lb - ls * 1.45f, value, fit(value, n.value, maxw, vs), vcol, Paint.Align.CENTER);
            } else {                                                    // under the node
                float maxw = Math.min(Math.min(2 * (nx - x - 4 * u), 2 * (x + w - 4 * u - nx)), R * 3.2f);
                float base = ny + R + 12 * u + vs * 0.8f;
                text(c, n.value, nx, base, value, fit(value, n.value, maxw, vs), vcol, Paint.Align.CENTER);
                text(c, n.label, nx, base + ls * 1.45f, label, fit(label, n.label, maxw, ls), colors[MUTED], Paint.Align.CENTER);
                if (!n.extra.isEmpty())
                    text(c, n.extra, nx, base + ls * 2.8f, label, fit(label, n.extra, maxw, ls * 0.92f), ecol, Paint.Align.CENTER);
            }
        }
        return moving;
    }

    // ------------------------------------------------------------ state-of-charge card

    private void battery(Canvas c, float[] rect) {
        State st = state;
        float x = rect[0], y = rect[1], w = rect[2], h = rect[3];
        float p = Math.min(16 * u, h * 0.14f), ls = Math.min(14 * u, h * 0.13f);
        text(c, lSoc, x + p, y + p + ascent(label, ls) * 0.8f, label, fit(label, lSoc, w * 0.5f, ls), colors[MUTED], Paint.Align.LEFT);
        float barH = Math.max(8 * u, h * 0.1f), barTop = y + h - p - barH;
        float areaTop = y + p + ls * 1.4f, areaBottom = barTop - p * 0.5f;
        int col = colors[st.socColor];
        float size = Math.min((areaBottom - areaTop) * 0.98f, fit(value, st.soc + "%", w * 0.5f, (areaBottom - areaTop) * 0.98f));
        value.setTextSize(size);
        float base = areaBottom - value.descent() * 0.25f;
        float nw = value.measureText(st.soc);
        text(c, st.soc, x + p, base, value, size, col, Paint.Align.LEFT);
        text(c, "%", x + p + nw + 3 * u, base, value, size * 0.4f, col, Paint.Align.LEFT);
        float rx = x + w * 0.52f;
        float vs = fit(value, st.time, x + w - p - rx, Math.min(26 * u, (areaBottom - areaTop) * 0.45f));
        text(c, st.time, rx, base, value, vs, st.stale ? colors[MUTED] : colors[TEXT], Paint.Align.LEFT);
        text(c, st.timeLabel, rx, base - vs * 1.05f, label, fit(label, st.timeLabel, x + w - p - rx, ls), colors[MUTED], Paint.Align.LEFT);
        float l = x + p, rt = x + w - p;
        rrect(c, l, barTop, rt - l, barH, barH / 2, track);
        if (st.barPercent > 0)
            rrect(c, l, barTop, Math.max((rt - l) * Math.min(100, st.barPercent) / 100, barH), barH, barH / 2, col);
    }

    // ------------------------------------------------------------ readings card

    private void readIcon(Canvas c, int i, float cx, float cy, float size) {
        icon(c, state.readIcon[i], cx, cy, size, source[state.readIconColor[i]], panel, -1);
    }

    private void readings(Canvas c, float[] rect) {
        State st = state;
        float x = rect[0], y = rect[1], w = rect[2], h = rect[3];
        float p = Math.min(16 * u, h * 0.08f), ts = Math.min(17 * u, h * 0.1f);
        float titleBase = y + p + ascent(value, ts) * 0.8f;
        text(c, lReadings, x + p, titleBase, value, fit(value, lReadings, w - 2 * p, ts), colors[TEXT], Paint.Align.LEFT);
        float gy = titleBase + p * 0.6f;
        if (w < 280 * u) { readingList(c, x + p, gy, w - 2 * p, y + h - p * 0.5f - gy); return; }
        float rh = (y + h - p * 0.6f - gy) / 3, cw = (w - 2 * p) / 2;
        float isz = Math.min(22 * u, rh * 0.5f), maxw = cw - isz - 18 * u;
        // one text size for every cell, so the six values line up
        float ls = Math.min(13 * u, rh * 0.26f), vs = Math.min(19 * u, rh * 0.36f);
        for (int i = 0; i < 6; i++) {
            ls = Math.min(ls, fit(label, st.readLabel[i], maxw, ls));
            vs = Math.min(vs, fit(value, st.readValue[i], maxw, vs));
        }
        for (int i = 0; i < 6; i++) {
            int row = i / 2, col = i % 2;
            float cx0 = x + p + col * cw, cy0 = gy + row * rh, mid = cy0 + rh / 2;
            if (row > 0 && col == 0) line(c, x + p, cy0, x + w - p, cy0, Math.max(1, u), line);
            readIcon(c, i, cx0 + isz / 2 + 2 * u, mid, isz);
            float tx = cx0 + isz + 12 * u;
            text(c, st.readLabel[i], tx, mid - rh * 0.06f, label, ls, colors[MUTED], Paint.Align.LEFT);
            text(c, st.readValue[i], tx, mid + vs * 0.95f, value, vs, colors[st.readValueColor[i]], Paint.Align.LEFT);
        }
    }

    /** Narrow cards: one list, values on the right. */
    private void readingList(Canvas c, float x, float y, float w, float h) {
        State st = state;
        float rh = h / 6, isz = Math.min(18 * u, rh * 0.62f), size = Math.min(15 * u, rh * 0.55f);
        value.setTextSize(size);
        float vw = 0;
        for (String v : st.readValue) vw = Math.max(vw, value.measureText(v));
        float lw = w - isz - 10 * u - vw - 8 * u, ls = size;
        for (String l : st.readLabel) ls = Math.min(ls, fit(label, l, lw, size));
        for (int i = 0; i < 6; i++) {
            float mid = y + i * rh + rh / 2, base = mid + ascent(label, size) * 0.36f;
            readIcon(c, i, x + isz / 2, mid, isz);
            text(c, st.readLabel[i], x + isz + 10 * u, base, label, ls, colors[MUTED], Paint.Align.LEFT);
            text(c, st.readValue[i], x + w, base, value, size, colors[st.readValueColor[i]], Paint.Align.RIGHT);
        }
    }

    // ------------------------------------------------------------ touch

    @Override public boolean onTouchEvent(MotionEvent e) {
        if (listener == null) return super.onTouchEvent(e);
        float x = e.getX(), y = e.getY();
        switch (e.getAction()) {
            case MotionEvent.ACTION_DOWN:
                cogPressed = cogHit.contains(x, y);
                if (cogPressed) invalidate();
                return true;
            case MotionEvent.ACTION_UP:
                if (cogPressed && cogHit.contains(x, y)) { performClick(); listener.onCogTapped(); }
                else if (!cogPressed && statusHit.contains(x, y)) listener.onStatusTapped();
                if (cogPressed) { cogPressed = false; invalidate(); }
                return true;
            case MotionEvent.ACTION_CANCEL:
                if (cogPressed) { cogPressed = false; invalidate(); }
                return true;
            default:
                return true;
        }
    }

    @Override public boolean performClick() { return super.performClick(); }

    /** With TalkBack, the whole dashboard is one item; double-tapping it opens settings. */
    @Override public boolean performAccessibilityAction(int action, android.os.Bundle args) {
        if (action == android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK && listener != null) {
            listener.onCogTapped();
            return true;
        }
        return super.performAccessibilityAction(action, args);
    }
}
