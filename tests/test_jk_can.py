"""Test cases from the published BMS-CAN protocol and one Pylon broadcast log.

Section 7 of the protocol PDF is titled "Test case". The numeric examples in
section 6 are the ones whose bytes and prose agree. Section 7.1 writes the
discharge-time bytes as 64 40 while still calling the value 100 h; 0x4064 is
not 100. Section 7.3 pastes the section 7.2 status payload onto ID 0x04F4 and
then describes the section 6.2 cell voltages. Those two payloads are not used
as passing fixtures.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from jk_can import (
    active_alarms,
    decode_alarm,
    decode_batt_st,
    decode_cell_temp,
    decode_cell_volt,
    decode_pylon_limits,
    decode_pylon_measure,
    decode_pylon_soc,
)

ROOT = Path(__file__).resolve().parents[1]
ESPHOME = ROOT / "esphome"


class InstrumentProtocolTest(unittest.TestCase):
    def test_normal_status_frame(self):
        # 6.1 example: 02F4 13 01 D7 11 33 XX 64 00
        frame = bytes.fromhex("13 01 D7 11 33 00 64 00")
        got = decode_batt_st(frame)
        self.assertAlmostEqual(got["voltage_v"], 27.5)
        self.assertAlmostEqual(got["current_a"], 56.7)
        self.assertEqual(got["soc_pct"], 51)
        self.assertEqual(got["discharge_time_h"], 100)
        self.assertAlmostEqual(got["voltage_v"] * got["current_a"], 1559.25)

    def test_low_battery_status_frame(self):
        # 7.2 example: E1 00 8A 10 10 XX XX XX
        frame = bytes.fromhex("E1 00 8A 10 10 00 00 00")
        got = decode_batt_st(frame)
        self.assertAlmostEqual(got["voltage_v"], 22.5)
        self.assertAlmostEqual(got["current_a"], 23.4)
        self.assertEqual(got["soc_pct"], 16)

    def test_cell_voltage_extremes(self):
        # 6.2 example: 8C 0A 05 92 09 08 XX XX
        frame = bytes.fromhex("8C 0A 05 92 09 08 00 00")
        got = decode_cell_volt(frame)
        self.assertAlmostEqual(got["max_cell_v"], 2.700)
        self.assertEqual(got["max_cell"], 5)
        self.assertAlmostEqual(got["min_cell_v"], 2.450)
        self.assertEqual(got["min_cell"], 8)

    def test_cell_temperature_frame(self):
        # 7.4 bytes. Average uses the -50 offset: 0x3F -> 13 C.
        # The PDF prose says 33 C for that same byte.
        frame = bytes.fromhex("48 06 2F 01 3F 00 00 00")
        got = decode_cell_temp(frame)
        self.assertEqual(got["max_c"], 22)
        self.assertEqual(got["max_cell"], 6)
        self.assertEqual(got["min_c"], -3)
        self.assertEqual(got["min_cell"], 1)
        self.assertEqual(got["average_c"], 13)

    def test_mixed_alarm_levels(self):
        # 6.4 example: 43 00 20 00
        levels = decode_alarm(bytes.fromhex("43 00 20 00 00 00 00 00"))
        self.assertEqual(
            active_alarms(levels),
            [
                ("cell_overvoltage", 3),
                ("pack_undervoltage", 1),
                ("soc_low", 2),
            ],
        )

    def test_soc_low_alarm(self):
        levels = decode_alarm(bytes.fromhex("00 00 30 00 00 00 00 00"))
        self.assertEqual(active_alarms(levels), [("soc_low", 3)])

    def test_cell_voltage_alarms(self):
        levels = decode_alarm(bytes.fromhex("0F 00 00 00 00 00 00 00"))
        self.assertEqual(
            active_alarms(levels),
            [("cell_overvoltage", 3), ("cell_undervoltage", 3)],
        )

    def test_temperature_alarms(self):
        levels = decode_alarm(bytes.fromhex("00 C0 03 00 00 00 00 00"))
        self.assertEqual(
            active_alarms(levels),
            [("temperature_high", 3), ("temperature_low", 3)],
        )

    def test_short_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_batt_st(bytes.fromhex("13 01"))


class PylonBroadcastTest(unittest.TestCase):
    def test_limits_frame(self):
        # Logged Pylon-style send: 28 02 E8 03 E8 03 A0 01
        frame = bytes.fromhex("28 02 E8 03 E8 03 A0 01")
        got = decode_pylon_limits(frame)
        self.assertAlmostEqual(got["charge_voltage_v"], 55.2)
        self.assertAlmostEqual(got["charge_current_limit_a"], 100.0)
        self.assertAlmostEqual(got["discharge_current_limit_a"], 100.0)
        self.assertAlmostEqual(got["discharge_voltage_v"], 41.6)

    def test_soc_frame(self):
        got = decode_pylon_soc(bytes.fromhex("4F 00 64 00"))
        self.assertEqual(got["soc_pct"], 79)
        self.assertEqual(got["soh_pct"], 100)

    def test_measure_frame_discharge_is_negative(self):
        frame = bytes.fromhex("63 14 62 FC 86 01")
        got = decode_pylon_measure(frame)
        self.assertAlmostEqual(got["voltage_v"], 52.19)
        self.assertAlmostEqual(got["current_a"], -92.6)
        self.assertAlmostEqual(got["temperature_c"], 39.0)


class DraftConfigTest(unittest.TestCase):
    def test_can_draft_matches_instrument_decoder(self):
        text = (ESPHOME / "b2a24s15p-can.yaml").read_text()
        for needle in (
            "0x02F4",
            "0x04F4",
            "0x05F4",
            "0x07F4",
            "250KBPS",
            "GPIO4",
            "GPIO5",
            "raw_i * 0.1f - 400.0f",
            "x[0] - 50",
            "SN65HVD230",
            "VGPS",
        ):
            self.assertIn(needle, text)

    def test_pylon_draft_matches_broadcast_decoder(self):
        text = (ESPHOME / "b2a24s15p-can-pylon.yaml").read_text()
        for needle in ("0x351", "0x355", "0x356", "500KBPS", "s16_i * 0.1f"):
            self.assertIn(needle, text)

    def test_uart_draft_reads_24_cells_and_blocks_vbat(self):
        text = (ESPHOME / "b2a24s15p-uart.yaml").read_text()
        self.assertIn("baud_rate: 115200", text)
        self.assertIn("tx_pin: GPIO16", text)
        self.assertIn("rx_pin: GPIO17", text)
        self.assertIn("cell_voltage_24:", text)
        self.assertIn("VGPS", text)
        self.assertNotIn("charging_switch", text)

    def test_ble_draft_is_read_only(self):
        text = (ESPHOME / "b2a24s15p-ble.yaml").read_text()
        self.assertIn("protocol_version: JK02_24S", text)
        self.assertIn("jk_bms_ble:", text)
        self.assertIn("jk_bms_ble_id: bms0", text)
        self.assertIn("cell_voltage_24:", text)
        self.assertNotIn("\nnumber:", text)
        self.assertNotIn("\nswitch:", text)
        self.assertNotIn("\nbutton:", text)

    def test_figures_exist(self):
        figures = ROOT / "docs" / "figures"
        for name in ("system.svg", "can-wiring.svg", "uart-gps.svg"):
            path = figures / name
            self.assertTrue(path.is_file(), name)
            body = path.read_text()
            self.assertIn("<svg", body)
            if name == "uart-gps.svg":
                self.assertIn("GPIO16", body)
                self.assertIn("VGPS", body)
            else:
                self.assertIn("CAN_H", body)


if __name__ == "__main__":
    unittest.main()
