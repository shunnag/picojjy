"""Host-side regression tests for main.py — no hardware required.

Run from the repository root:

    python3 -m unittest discover tests

Hardware modules (machine, network, micropython) are stubbed before
importing main.py; the __name__ guard at its bottom keeps the
transmitter from starting.  These tests cover the pure logic only:
JJY frame construction, power-save window arithmetic and the NTP
timestamp math.
"""

import calendar
import os
import random
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_stubs():
    machine = types.ModuleType("machine")

    class _Pin:
        OUT = 1

        def __init__(self, *args, **kwargs):
            pass

        def value(self, *args):
            pass

        def toggle(self):
            pass

    class _PWM(_Pin):
        def freq(self, *args):
            pass

        def duty_u16(self, *args):
            pass

    machine.Pin = _Pin
    machine.PWM = _PWM
    machine.WDT = lambda **kwargs: None
    machine.freq = lambda *args: 125000000
    machine.lightsleep = lambda ms: None
    machine.reset = lambda: None
    sys.modules.setdefault("machine", machine)

    network = types.ModuleType("network")
    network.STA_IF = 0

    class _WLAN:
        PM_PERFORMANCE = 0xA11142

        def __init__(self, *args, **kwargs):
            pass

    network.WLAN = _WLAN
    sys.modules.setdefault("network", network)

    micropython = types.ModuleType("micropython")
    micropython.const = lambda x: x
    sys.modules.setdefault("micropython", micropython)


_install_stubs()
import main  # noqa: E402  (the __main__ guard keeps it from running)


def reference_frame(tm):
    """JJY frame derived independently from the spec (not from main.py).

    Positions per the published JJY time-code table: minute BCD at
    seconds 1-8, hour at 12-18, day-of-year at 22-33, parity at 36/37,
    year (2 digits) at 41-48, day-of-week at 50-52, markers at every
    multiple of 10 minus one plus second 0.
    """
    frame = ["0"] * 60
    for sec in (0, 9, 19, 29, 39, 49, 59):
        frame[sec] = "M"

    def digit_bits(digit, n):
        return [(digit >> i) & 1 for i in range(n - 1, -1, -1)]

    def put(secs, bits):
        for sec, bit in zip(secs, bits):
            frame[sec] = str(bit)

    minute, hour, yday, year = tm[4], tm[3], tm[7], tm[0]
    put((1, 2, 3), digit_bits(minute // 10, 3))
    put((5, 6, 7, 8), digit_bits(minute % 10, 4))
    put((12, 13), digit_bits(hour // 10, 2))
    put((15, 16, 17, 18), digit_bits(hour % 10, 4))
    put((22, 23), digit_bits(yday // 100, 2))
    put((25, 26, 27, 28), digit_bits(yday // 10 % 10, 4))
    put((30, 31, 32, 33), digit_bits(yday % 10, 4))
    put((41, 42, 43, 44), digit_bits(year % 100 // 10, 4))
    put((45, 46, 47, 48), digit_bits(year % 10, 4))
    # ISO weekday: Mon=1 .. Sun=7; JJY: Sun=0 .. Sat=6.
    iso_dow = calendar.weekday(tm[0], tm[1], tm[2]) + 1
    put((50, 51, 52), digit_bits(iso_dow % 7, 3))
    # PA1 (36): even parity over hour bits; PA2 (37): over minute bits.
    frame[36] = str(sum(int(frame[s]) for s in (12, 13, 15, 16, 17, 18)) % 2)
    frame[37] = str(sum(int(frame[s]) for s in (1, 2, 3, 5, 6, 7, 8)) % 2)
    return "".join(frame)


def frame_str(frame):
    return "".join("M" if sym == main._MARK else str(sym) for sym in frame)


def sample_timestamps():
    ts = []
    for y, mo, d, h, mi in (
        (2026, 1, 1, 0, 0),
        (2026, 7, 25, 23, 45),
        (2026, 12, 31, 23, 59),
        (2027, 1, 1, 0, 0),      # year rollover
        (2028, 2, 29, 12, 34),   # leap day
        (2028, 12, 31, 11, 30),  # doy 366
        (2029, 4, 9, 10, 0),     # BCD digit edges
        (2030, 10, 19, 19, 20),
        (2099, 12, 31, 9, 59),   # year % 100 upper edge
    ):
        ts.append(calendar.timegm((y, mo, d, h, mi, 0, 0, 0, 0)))
    rng = random.Random(20260725)
    start = calendar.timegm((2000, 1, 1, 0, 0, 0, 0, 0, 0))
    end = calendar.timegm((2099, 12, 31, 0, 0, 0, 0, 0, 0))
    ts.extend(rng.randrange(start, end, 60) for _ in range(500))
    return ts


class FrameTests(unittest.TestCase):
    def test_against_spec_reference(self):
        buf = bytearray(60)
        for t in sample_timestamps():
            tm = time.gmtime(t)
            got = frame_str(main.build_frame(tm, buf))
            self.assertEqual(got, reference_frame(tm),
                             "frame mismatch at %s" % (tm,))

    def test_symbol_codes_and_durations(self):
        buf = bytearray(60)
        frame = main.build_frame(time.gmtime(0), buf)
        self.assertLessEqual(set(frame), {0, 1, main._MARK})
        self.assertEqual(main.SYMBOL_ON_MS[0], 800)
        self.assertEqual(main.SYMBOL_ON_MS[1], 500)
        self.assertEqual(main.SYMBOL_ON_MS[main._MARK], 200)

    def test_buffer_reuse_leaves_no_stale_bits(self):
        reused = bytearray(60)
        t0 = calendar.timegm((2026, 12, 31, 23, 58, 0, 0, 0, 0))
        for i in range(120):  # crosses a year boundary minute by minute
            tm = time.gmtime(t0 + 60 * i)
            main.build_frame(tm, reused)
            fresh = main.build_frame(tm, bytearray(60))
            self.assertEqual(bytes(reused), bytes(fresh))

    def test_returns_the_given_buffer(self):
        buf = bytearray(60)
        self.assertIs(main.build_frame(time.gmtime(0), buf), buf)


class WindowTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(main.parse_windows(("11:45-12:15", "23:45-00:15")),
                         [(42300, 44100), (85500, 900)])

    def test_parse_rejects_bad_specs(self):
        for spec in ("1145-1215", "11:45", "24:00-01:00", "11:60-12:00",
                     "12:00-12:00", "aa:bb-cc:dd", ""):
            with self.assertRaises(ValueError, msg=spec):
                main.parse_windows((spec,))
        with self.assertRaises(ValueError):
            main.parse_windows(())

    def test_remaining_and_delta(self):
        w = main.parse_windows(("11:45-12:15", "23:45-00:15"))
        self.assertEqual(main.window_remaining(w, 42300), 1800)  # 11:45:00
        self.assertEqual(main.window_remaining(w, 44099), 1)     # 12:14:59
        self.assertEqual(main.window_remaining(w, 44100), 0)     # 12:15:00
        self.assertEqual(main.window_remaining(w, 0), 900)       # 00:00:00
        self.assertEqual(main.window_remaining(w, 899), 1)       # 00:14:59
        self.assertEqual(main.window_remaining(w, 900), 0)       # 00:15:00
        self.assertEqual(main.next_window_delta(w, 42300), 0)
        self.assertEqual(main.next_window_delta(w, 42299), 1)
        self.assertEqual(main.next_window_delta(w, 44100), 41400)  # -> 23:45
        self.assertEqual(main.next_window_delta(w, 86399), 42301)

    def test_midnight_crossing_window(self):
        (w,) = [main.parse_windows(("23:00-01:00",))[0]]
        windows = [w]
        self.assertEqual(main.window_remaining(windows, 82800), 7200)
        self.assertEqual(main.window_remaining(windows, 0), 3600)
        self.assertEqual(main.window_remaining(windows, 3600), 0)


class NtpMathTests(unittest.TestCase):
    def test_delta_constants(self):
        # 2208988800 s = 1900-01-01 -> 1970-01-01; the 2000-epoch value
        # must equal it plus the 1970 -> 2000 span (derivation check,
        # independent of which branch the host picked).
        self.assertIn(main.NTP_DELTA, (2208988800, 3155673600))
        self.assertEqual(
            3155673600,
            2208988800 + calendar.timegm((2000, 1, 1, 0, 0, 0, 0, 0, 0)))
        self.assertEqual(main.NTP_DELTA,
                         3155673600 if time.gmtime(0)[0] == 2000
                         else 2208988800)

    def test_timestamp_conversion(self):
        base = main.NTP_DELTA + 1000
        self.assertEqual(main._ntp_utc_ms(base, 0), 1000000)
        self.assertEqual(main._ntp_utc_ms(base, 1 << 31), 1000500)
        self.assertEqual(main._ntp_utc_ms(base, (1 << 32) - 1), 1000999)
        # Sub-millisecond fractions floor to 0 ms.
        self.assertEqual(main._ntp_utc_ms(base, 1), 1000000)
        self.assertEqual(main._ntp_utc_ms(main.NTP_DELTA, 0), 0)


class BcdBitTests(unittest.TestCase):
    def test_all_weights(self):
        for value in range(0, 400, 3):
            digits = (value % 10, value // 10 % 10, value // 100 % 10)
            for weight in (1, 2, 4, 8, 10, 20, 40, 80, 100, 200):
                digit = digits[0 if weight < 10 else (1 if weight < 100 else 2)]
                mask = weight if weight < 10 else (
                    weight // 10 if weight < 100 else weight // 100)
                want = 1 if digit & mask else 0
                self.assertEqual(main._bcd_bit(value, weight), want,
                                 "value=%d weight=%d" % (value, weight))


if __name__ == "__main__":
    unittest.main()
