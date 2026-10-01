package dngsoftware.shuntdisplay;

/** One decoded reading from a battery monitor. Missing values are NaN (or -1 for remainingMins). */
public final class ShuntReading {
    public static final int AUX_STARTER = 0, AUX_MIDPOINT = 1, AUX_TEMPERATURE = 2, AUX_NONE = 3;

    public float voltage = Float.NaN;      // V
    public float current = Float.NaN;      // A, + charging / - discharging
    public float soc = Float.NaN;          // %
    public float consumedAh = Float.NaN;   // Ah (zero or negative)
    public int remainingMins = -1;         // -1 = not available
    public int alarm = 0;                  // bit field, see VictronDecoder.alarmText()
    public int auxMode = AUX_NONE;
    public float aux = Float.NaN;          // starter/midpoint volts, or temperature in °C
    public int modelId = 0;

    /** Power in watts, or NaN. */
    public float power() {
        return Float.isNaN(voltage) || Float.isNaN(current) ? Float.NaN : voltage * current;
    }
}
