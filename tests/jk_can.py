"""Decoders for the two CAN layouts drafted in esphome/.

The instrument layout is the published BMS-CAN protocol: CAN 2.0A, 250 kbit/s,
standard IDs, BMS source address 0xF4. Multi-byte fields are little-endian.
Pack current uses offset -400 A, and a positive result is discharge.

The Pylon layout is the low-voltage battery broadcast used by many inverter
profiles (500 kbit/s). There, a positive current is charge.
"""

from __future__ import annotations

INSTRUMENT_IDS = {
    "batt_st": 0x02F4,
    "cell_volt": 0x04F4,
    "cell_temp": 0x05F4,
    "alarm": 0x07F4,
}

PYLON_IDS = {
    "limits": 0x351,
    "soc": 0x355,
    "measure": 0x356,
}

ALARM_NAMES = (
    "cell_overvoltage",
    "cell_undervoltage",
    "pack_overvoltage",
    "pack_undervoltage",
    "cell_delta",
    "discharge_overcurrent",
    "charge_overcurrent",
    "temperature_high",
    "temperature_low",
    "temperature_delta",
    "soc_low",
    "insulation_low",
    "hv_interlock",
    "external_comms",
    "internal_comms",
)

ALARM_LEVEL = {0: "none", 1: "severe", 2: "important", 3: "general"}


def u16_le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def s16_le(data: bytes, offset: int) -> int:
    value = u16_le(data, offset)
    return value - 0x10000 if value & 0x8000 else value


def _need(data: bytes, size: int, name: str) -> None:
    if len(data) < size:
        raise ValueError(f"{name} frame needs {size} bytes, got {len(data)}")


def decode_batt_st(data: bytes) -> dict:
    """ID 0x02F4. Current is amperes, positive while discharging."""
    _need(data, 8, "BATT_ST")
    return {
        "voltage_v": u16_le(data, 0) * 0.1,
        "current_a": u16_le(data, 2) * 0.1 - 400.0,
        "soc_pct": data[4],
        "discharge_time_h": u16_le(data, 6),
    }


def decode_cell_volt(data: bytes) -> dict:
    """ID 0x04F4. Cell numbers are the 1-based values carried in the frame.

    The PDF table places the minimum at bit 32. The worked example
    ``8C 0A 05 92 09 08`` only produces 2450 mV and cell 8 when the minimum
    starts at byte 3, immediately after the maximum-cell number.
    """
    _need(data, 6, "CELL_VOLT")
    return {
        "max_cell_v": u16_le(data, 0) / 1000.0,
        "max_cell": data[2],
        "min_cell_v": u16_le(data, 3) / 1000.0,
        "min_cell": data[5],
    }


def decode_cell_temp(data: bytes) -> dict:
    """ID 0x05F4. Temperatures are degrees Celsius, offset -50 in the byte."""
    _need(data, 5, "CELL_TEMP")

    def celsius(raw: int) -> int:
        return raw - 50

    return {
        "max_c": celsius(data[0]),
        "max_cell": data[1],
        "min_c": celsius(data[2]),
        "min_cell": data[3],
        "average_c": celsius(data[4]),
    }


def decode_alarm(data: bytes) -> dict:
    """ID 0x07F4. Each alarm is a 2-bit level packed from bit 0 upward."""
    _need(data, 4, "ALM_INFO")
    bits = int.from_bytes(data[:4], "little")
    levels = {}
    for index, name in enumerate(ALARM_NAMES):
        levels[name] = (bits >> (2 * index)) & 0x3
    return levels


def active_alarms(levels: dict) -> list[tuple[str, int]]:
    return [(name, level) for name, level in levels.items() if level]


def decode_pylon_limits(data: bytes) -> dict:
    """ID 0x351. Limits are unsigned, 0.1 V and 0.1 A."""
    _need(data, 8, "PYLON_351")
    return {
        "charge_voltage_v": u16_le(data, 0) * 0.1,
        "charge_current_limit_a": u16_le(data, 2) * 0.1,
        "discharge_current_limit_a": u16_le(data, 4) * 0.1,
        "discharge_voltage_v": u16_le(data, 6) * 0.1,
    }


def decode_pylon_soc(data: bytes) -> dict:
    """ID 0x355. SOC and SOH are percent."""
    _need(data, 4, "PYLON_355")
    return {"soc_pct": u16_le(data, 0), "soh_pct": u16_le(data, 2)}


def decode_pylon_measure(data: bytes) -> dict:
    """ID 0x356. Current is amperes and positive while charging."""
    _need(data, 6, "PYLON_356")
    return {
        "voltage_v": u16_le(data, 0) * 0.01,
        "current_a": s16_le(data, 2) * 0.1,
        "temperature_c": s16_le(data, 4) * 0.1,
    }
