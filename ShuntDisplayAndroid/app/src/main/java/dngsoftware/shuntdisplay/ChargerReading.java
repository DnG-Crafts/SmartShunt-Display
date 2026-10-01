package dngsoftware.shuntdisplay;

/**
 * One decoded reading from a Victron charger: a Blue Smart IP22 (or other AC charger), a solar
 * charger (MPPT) or an Orion XS DC-DC charger. Missing values are NaN, or -1 for state and error.
 */
public final class ChargerReading {
    public static final int KIND_MAINS = 0, KIND_SOLAR = 1, KIND_DCDC = 2;

    public int kind;
    public int state = -1;                 // Victron operation mode: 0 off, 3 bulk, 4 absorption, 5 float…
    public int error = -1;                 // charger error code, 0 = none
    public float voltage = Float.NaN;      // V, output 1
    public float current = Float.NaN;      // A, all outputs
    public float power = Float.NaN;        // W going out to the batteries
    public int modelId = 0;
}
