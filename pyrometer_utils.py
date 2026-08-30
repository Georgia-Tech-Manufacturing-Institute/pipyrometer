"""
    Pyrometer-specific helpers for the MCC 118 DAQ scripts as well as 
    daqhat_utils from examples

    Keep the voltage->temperature mapping here so both the threaded and socket
    scripts share one definition.

"""

# Pyrometer analog-output calibration (edit these if the sensor is reconfigured).
PYRO_V_MIN = 0.0      # Volts at the low end of the range
PYRO_V_MAX = 10.0     # Volts at the high end of the range
PYRO_T_MIN = 490.0    # Temperature (deg C) corresponding to PYRO_V_MIN
PYRO_T_MAX = 2000.0   # Temperature (deg C) corresponding to PYRO_V_MAX

# Slope of the linear map, deg C per Volt (= 151.0 for the defaults above).
_SLOPE = (PYRO_T_MAX - PYRO_T_MIN) / (PYRO_V_MAX - PYRO_V_MIN)


def volts_to_temperature(volts):
    # type: (float) -> tuple[float, bool]
    """
    Convert a pyrometer output voltage to temperature in degrees Celsius.

    The conversion is linear:
        T = PYRO_T_MIN + volts * (PYRO_T_MAX - PYRO_T_MIN) / (PYRO_V_MAX - PYRO_V_MIN)

    The temperature is returned for the raw voltage even when it is outside the
    nominal 0 - 10 V window (so brief noise excursions are still visible); the
    second return value flags whether the reading was out of range.

    Args:
        volts (float): Measured voltage from the pyrometer (MCC 118 channel).

    Returns:
        tuple[float, bool]: (temperature_C, out_of_range) where out_of_range is
        True if volts is below PYRO_V_MIN or above PYRO_V_MAX.
    """
    temperature_c = PYRO_T_MIN + (volts - PYRO_V_MIN) * _SLOPE
    out_of_range = volts < PYRO_V_MIN or volts > PYRO_V_MAX
    return temperature_c, out_of_range


if __name__ == '__main__':
    # Quick sanity check of conversion 
    #   0 V -> 490 C, 5 V -> 1245 C, 10 V -> 2000 C
    for v in (0.0, 2.5, 5.0, 7.5, 10.0):
        t, oor = volts_to_temperature(v)
        print('{:6.2f} V -> {:8.2f} C  (out_of_range={})'.format(v, t, oor))
