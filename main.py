"""picojjy - JJY (Japanese longwave time signal) simulator for
Raspberry Pi Pico W / Raspberry Pi Pico 2 W (MicroPython).

Connects to Wi-Fi, synchronizes with an NTP server (ntp.nict.jp by
default) and emits the JJY amplitude-modulated time code on a GPIO pin
as a 40 kHz / 60 kHz PWM carrier.  Place a small antenna wire connected
to that pin near a radio-controlled clock to let it synchronize.

JJY time code summary (one frame = 60 seconds, one symbol per second):
    marker "M" : carrier ON for 0.2 s
    binary 1   : carrier ON for 0.5 s
    binary 0   : carrier ON for 0.8 s
The carrier is switched OFF for the remainder of each second.  Real JJY
lowers the carrier to 10 % power instead of switching it off, but plain
on-off keying is decoded fine by consumer clocks.

All user settings live in config.py.
"""

import struct
import time

import machine
import network
import socket
from machine import Pin, PWM

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Offset from the NTP epoch (1900-01-01) to this port's time.gmtime()
# epoch.  Embedded MicroPython ports use 2000-01-01, others 1970-01-01.
NTP_DELTA = 3155673600 if time.gmtime(0)[0] == 2000 else 2208988800

# Carrier-ON duration in milliseconds for each JJY symbol.
SYMBOL_ON_MS = {"M": 200, 1: 500, 0: 800}

# (second-in-frame, BCD weight) pairs for each field of the JJY frame.
_MINUTE_SLOTS = ((1, 40), (2, 20), (3, 10), (5, 8), (6, 4), (7, 2), (8, 1))
_HOUR_SLOTS = ((12, 20), (13, 10), (15, 8), (16, 4), (17, 2), (18, 1))
_YDAY_SLOTS = ((22, 200), (23, 100), (25, 80), (26, 40), (27, 20), (28, 10),
               (30, 8), (31, 4), (32, 2), (33, 1))
_YEAR_SLOTS = ((41, 80), (42, 40), (43, 20), (44, 10),
               (45, 8), (46, 4), (47, 2), (48, 1))
_DOW_SLOTS = ((50, 4), (51, 2), (52, 1))

# Seconds that carry a position marker (M, P1..P5, P0).  P0 (59) followed
# by M (0) gives receivers two consecutive markers to find the minute edge.
_MARKER_SECONDS = (0, 9, 19, 29, 39, 49, 59)


# ---------------------------------------------------------------------------
# Hardware watchdog
# ---------------------------------------------------------------------------

# Set in main() when config.WATCHDOG is True.  The RP2040/RP2350 watchdog
# allows at most ~8.3 s, so every blocking wait below is chopped into
# pieces short enough to call _feed() in between.
_wdt = None


def _feed():
    if _wdt:
        _wdt.feed()


# ---------------------------------------------------------------------------
# NTP-synchronized millisecond clock
# ---------------------------------------------------------------------------

class SyncedClock:
    """Millisecond UTC wall clock anchored to one NTP measurement.

    The NTP result is tied to a time.ticks_ms() reading, so the current
    time can be read at any moment without touching the network.  The
    Pico crystal (~30 ppm) drifts only a few ms per hour, which is well
    within what radio-controlled clocks tolerate; periodic re-syncs keep
    the error bounded.
    """

    def __init__(self):
        self._anchor_ms = 0
        self._anchor_ticks = time.ticks_ms()

    def set(self, utc_ms, anchor_ticks):
        self._anchor_ms = utc_ms
        self._anchor_ticks = anchor_ticks

    def now_ms(self):
        """UTC milliseconds since the port epoch."""
        return self._anchor_ms + time.ticks_diff(time.ticks_ms(),
                                                 self._anchor_ticks)


def ntp_time(server, timeout_s):
    """Query an NTP server once.

    Returns (utc_ms, anchor_ticks): the server time in UTC milliseconds
    (port epoch) and the local ticks_ms() value it corresponds to.  The
    network delay is assumed symmetric, so the anchor is placed at the
    midpoint of the request round trip.
    """
    _feed()  # DNS lookup and the query below may block for seconds
    addr = socket.getaddrinfo(server, 123)[0][-1]
    _feed()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout_s)
        pkt = bytearray(48)
        pkt[0] = 0x1B  # LI=0, VN=3, Mode=3 (client)
        t_send = time.ticks_ms()
        sock.sendto(pkt, addr)
        data, _ = sock.recvfrom(48)
        t_recv = time.ticks_ms()
    finally:
        sock.close()
    _feed()
    if len(data) < 48:
        raise OSError("short NTP response")
    # Transmit timestamp: 32-bit seconds + 32-bit fraction, big endian.
    secs, frac = struct.unpack("!II", data[40:48])
    utc_ms = (secs - NTP_DELTA) * 1000 + (frac * 1000 >> 32)
    rtt = time.ticks_diff(t_recv, t_send)
    anchor_ticks = time.ticks_add(t_send, rtt // 2)
    return utc_ms, anchor_ticks


# ---------------------------------------------------------------------------
# JJY frame construction
# ---------------------------------------------------------------------------

def _bcd_bit(value, weight):
    """Return one bit of a BCD-coded value for a JJY weight (1..200)."""
    if weight >= 100:
        digit, mask = (value // 100) % 10, weight // 100
    elif weight >= 10:
        digit, mask = (value // 10) % 10, weight // 10
    else:
        digit, mask = value % 10, weight
    return 1 if digit & mask else 0


def build_frame(tm):
    """Build one 60-symbol JJY frame for the minute given by `tm`.

    `tm` is a time.gmtime() tuple of the JST time at the start of the
    minute.  Entries are "M" (marker), 0 or 1.

    Simplification: the call-sign / service-interruption variant that
    real JJY transmits during minutes 15 and 45 is not reproduced;
    consumer clocks decode the standard frame at those minutes as well.
    Leap-second bits (53, 54) are always 0.
    """
    year, hour, minute = tm[0], tm[3], tm[4]
    yday = tm[7]
    dow = (tm[6] + 1) % 7  # gmtime: 0=Monday -> JJY: 0=Sunday

    frame = [0] * 60
    for sec in _MARKER_SECONDS:
        frame[sec] = "M"
    for sec, w in _MINUTE_SLOTS:
        frame[sec] = _bcd_bit(minute, w)
    for sec, w in _HOUR_SLOTS:
        frame[sec] = _bcd_bit(hour, w)
    for sec, w in _YDAY_SLOTS:
        frame[sec] = _bcd_bit(yday, w)
    for sec, w in _YEAR_SLOTS:
        frame[sec] = _bcd_bit(year % 100, w)
    for sec, w in _DOW_SLOTS:
        frame[sec] = _bcd_bit(dow, w)
    # PA1 / PA2: even parity over the hour / minute bits.
    frame[36] = sum(frame[s] for s, _ in _HOUR_SLOTS) % 2
    frame[37] = sum(frame[s] for s, _ in _MINUTE_SLOTS) % 2
    return frame


# ---------------------------------------------------------------------------
# Wi-Fi / NTP helpers
# ---------------------------------------------------------------------------

def connect_wifi(led):
    """Bring up the Wi-Fi station interface, blocking until connected."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        # Disable Wi-Fi power save so NTP round trips stay short.
        wlan.config(pm=0xA11140)
    except (ValueError, OSError):
        pass
    if not wlan.isconnected():
        print("Connecting to Wi-Fi SSID:", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(),
                                  config.WIFI_TIMEOUT_S * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise OSError("Wi-Fi connect timeout")
            if led:
                led.toggle()
            _feed()
            time.sleep_ms(250)
    if led:
        led.value(0)
    print("Wi-Fi connected, IP:", wlan.ifconfig()[0])
    return wlan


def sync_clock(clock):
    """Sync `clock` from the configured NTP server, with retries.

    Returns True on success, False if every attempt failed.
    """
    for attempt in range(config.NTP_RETRIES):
        try:
            utc_ms, anchor = ntp_time(config.NTP_SERVER, config.NTP_TIMEOUT_S)
            clock.set(utc_ms, anchor)
            t = time.gmtime(utc_ms // 1000
                            + config.TIME_OFFSET_HOURS * 3600)
            print("NTP sync OK: %04d-%02d-%02d %02d:%02d:%02d (local)"
                  % (t[0], t[1], t[2], t[3], t[4], t[5]))
            return True
        except OSError as exc:
            print("NTP attempt %d/%d failed: %s"
                  % (attempt + 1, config.NTP_RETRIES, exc))
            _feed()
            time.sleep_ms(1000)
    return False


# ---------------------------------------------------------------------------
# Main transmit loop
# ---------------------------------------------------------------------------

def main():
    global _wdt
    if config.JJY_FREQUENCY_KHZ not in (40, 60):
        raise ValueError("JJY_FREQUENCY_KHZ must be 40 or 60")

    if getattr(config, "WATCHDOG", False):
        # A single NTP receive must stay comfortably inside the 8 s
        # watchdog window, since there is no way to feed mid-recvfrom.
        if config.NTP_TIMEOUT_S > 7:
            raise ValueError("NTP_TIMEOUT_S must be <= 7 when WATCHDOG is on")
        # Note: once started, the RP2 watchdog cannot be stopped until
        # the next reset.
        _wdt = machine.WDT(timeout=8000)
        print("Hardware watchdog enabled (8 s timeout)")

    led = Pin("LED", Pin.OUT) if config.STATUS_LED else None
    pwm = PWM(Pin(config.ANTENNA_PIN))
    pwm.freq(config.JJY_FREQUENCY_KHZ * 1000)
    pwm.duty_u16(0)
    duty_on = int(config.CARRIER_DUTY * 65535)

    def carrier(on):
        pwm.duty_u16(duty_on if on else 0)
        if led:
            # The LED mirrors the modulation: pulse length shows the
            # current symbol (0.2 s = marker, 0.5 s = 1, 0.8 s = 0).
            led.value(1 if on else 0)

    clock = SyncedClock()

    def wait_until(target_ms):
        """Block until clock.now_ms() reaches target_ms (ms precision)."""
        remaining = target_ms - clock.now_ms()
        while remaining > 10:
            _feed()
            # Sleep in <=1 s slices so the watchdog stays fed even
            # across an unexpectedly long wait.
            time.sleep_ms(min(remaining - 10, 1000))
            remaining = target_ms - clock.now_ms()
        while clock.now_ms() < target_ms:
            pass

    wlan = connect_wifi(led)
    if not sync_clock(clock):
        raise OSError("initial NTP sync failed")

    offset_ms = config.TIME_OFFSET_HOURS * 3600 * 1000
    resync_ms = config.NTP_RESYNC_MINUTES * 60 * 1000
    last_sync = clock.now_ms()

    print("Transmitting JJY on GPIO%d at %d kHz"
          % (config.ANTENNA_PIN, config.JJY_FREQUENCY_KHZ))

    frame = None
    # Index of the next local (JST) second to transmit.
    next_idx = (clock.now_ms() + offset_ms) // 1000 + 1

    while True:
        sec = next_idx % 60
        if frame is None or sec == 0:
            tm = time.gmtime(next_idx)
            frame = build_frame(tm)
            if sec == 0:
                print("Frame %02d:%02d (doy %d)" % (tm[3], tm[4], tm[7]))

        boundary = next_idx * 1000 - offset_ms  # UTC ms of second start
        if boundary - clock.now_ms() < -100:
            # We fell behind (e.g. a slow NTP re-sync or a backward time
            # step): realign to the next full second and rebuild.
            next_idx = (clock.now_ms() + offset_ms) // 1000 + 1
            frame = None
            continue

        wait_until(boundary)
        carrier(True)
        wait_until(boundary + SYMBOL_ON_MS[frame[sec]])
        carrier(False)

        # Housekeeping in the carrier-off tail of second 59, so a slow
        # NTP query corrupts at most the frame boundary.
        if sec == 59 and clock.now_ms() - last_sync >= resync_ms:
            if not wlan.isconnected():
                print("Wi-Fi lost, reconnecting...")
                try:
                    wlan = connect_wifi(led)
                except OSError as exc:
                    print("Reconnect failed: %s (free-running)" % exc)
            if wlan.isconnected() and sync_clock(clock):
                last_sync = clock.now_ms()
            else:
                # Keep transmitting on the free-running crystal and try
                # again after the next frame.
                last_sync += 60 * 1000

        next_idx += 1


try:
    main()
except Exception as exc:
    print("Fatal error:", exc)
    if getattr(config, "RESET_ON_ERROR", True):
        print("Resetting in 10 s...")
        for _ in range(10):
            _feed()
            time.sleep(1)
        machine.reset()
    else:
        # With WATCHDOG enabled the board still resets ~8 s from now,
        # because nothing feeds the watchdog anymore.
        raise
