from daqhats import hat_list, HatError

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

"""
    This file contains helper functions for the MCC DAQ HAT Python examples.
"""

def select_hat_device(filter_by_id):
    # type: (HatIDs) -> int
    """
    This function performs a query of available DAQ HAT devices and determines
    the address of a single DAQ HAT device to be used in an example.  If a
    single HAT device is present, the address for that device is automatically
    selected, otherwise the user is prompted to select an address from a list
    of displayed devices.

    Args:
        filter_by_id (int): If this is :py:const:`HatIDs.ANY` return all DAQ
            HATs found.  Otherwise, return only DAQ HATs with ID matching this
            value.

    Returns:
        int: The address of the selected device.

    Raises:
        Exception: No HAT devices are found or an invalid address was selected.

    """
    selected_hat_address = None

    # Get descriptors for all of the available HAT devices.
    hats = hat_list(filter_by_id=filter_by_id)
    number_of_hats = len(hats)

    # Verify at least one HAT device is detected.
    if number_of_hats < 1:
        raise HatError(0, 'Error: No HAT devices found')
    elif number_of_hats == 1:
        selected_hat_address = hats[0].address
    else:
        # Display available HAT devices for selection.
        for hat in hats:
            print('Address ', hat.address, ': ', hat.product_name, sep='')
        print('')

        address = int(input('Select the address of the HAT device to use: '))

        # Verify the selected address if valid.
        for hat in hats:
            if address == hat.address:
                selected_hat_address = address
                break

    if selected_hat_address is None:
        raise ValueError('Error: Invalid HAT selection')

    return selected_hat_address


def enum_mask_to_string(enum_type, bit_mask):
    # type: (Enum, int) -> str
    """
    This function converts a mask of values defined by an IntEnum class to a
    comma separated string of names corresponding to the IntEnum names of the
    values included in a bit mask.

    Args:
        enum_type (Enum): The IntEnum class from which the mask was created.
        bit_mask (int): A bit mask of values defined by the enum_type class.

    Returns:
        str: A comma separated string of names corresponding to the IntEnum
        names of the values included in the mask

    """
    item_names = []
    if bit_mask == 0:
        item_names.append('DEFAULT')
    for item in enum_type:
        if item & bit_mask:
            item_names.append(item.name)
    return ', '.join(item_names)


def chan_list_to_mask(chan_list):
    # type: (list[int]) -> int
    """
    This function returns an integer representing a channel mask to be used
    with the MCC daqhats library with all bit positions defined in the
    provided list of channels to a logic 1 and all other bit positions set
    to a logic 0.

    Args:
        chan_list (int): A list of channel numbers.

    Returns:
        int: A channel mask of all channels defined in chan_list.

    """
    chan_mask = 0

    for chan in chan_list:
        chan_mask |= 0x01 << chan

    return chan_mask


def validate_channels(channel_set, number_of_channels):
    # type: (set, int) -> None
    """
    Raises a ValueError exception if a channel number in the set of
    channels is not in the range of available channels.

    Args:
        channel_set (set): A set of channel numbers.
        number_of_channels (int): The number of available channels.

    Returns:
        None

    Raises:
        ValueError: If there is an invalid channel specified.

    """
    valid_chans = range(number_of_channels)
    if not channel_set.issubset(valid_chans):
        raise ValueError('Error: Invalid channel selected - must be '
                         '{} - {}'.format(min(valid_chans), max(valid_chans)))
    
if __name__ == '__main__':
    # Quick sanity check of conversion 
    #   0 V -> 490 C, 5 V -> 1245 C, 10 V -> 2000 C
    for v in (0.0, 2.5, 5.0, 7.5, 10.0):
        t, oor = volts_to_temperature(v)
        print('{:6.2f} V -> {:8.2f} C  (out_of_range={})'.format(v, t, oor))
