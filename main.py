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


class NTPClient:
    """NTP client with a bounded, non-blocking query.

    query() polls a non-blocking socket for at most `budget_ms`, so a
    call fits inside the carrier-off tail of a JJY second and the
    transmission never stalls on a slow server or a dead network.  The
    server address is cached, so the (blocking) DNS lookup normally
    happens only on the very first call.
    """

    def __init__(self, server):
        self.server = server
        self._addr = None
        self._sock = None
        self._failures = 0

    def _setup(self):
        if self._addr is None:
            _feed()  # DNS resolution may block for a while
            self._addr = socket.getaddrinfo(self.server, 123,
                                            socket.AF_INET,
                                            socket.SOCK_DGRAM)[0][-1]
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setblocking(False)

    def _note_failure(self):
        self._failures += 1
        if self._failures >= 10:
            # Repeated failures: the server address may have changed,
            # force a fresh DNS lookup on the next attempt.
            self._addr = None
            self._failures = 0

    def close(self):
        """Drop the socket (call before Wi-Fi is torn down)."""
        if self._sock:
            self._sock.close()
            self._sock = None

    def query(self, budget_ms):
        """One query attempt, waiting at most budget_ms for the reply.

        Returns (utc_ms, anchor_ticks) — the server time in UTC
        milliseconds (port epoch) and the ticks_ms() value it
        corresponds to (midpoint of the round trip, assuming a symmetric
        network delay) — or None on timeout/error.  A reply that arrives
        after the budget is drained and discarded on the next call: its
        round trip cannot be measured, so anchoring the clock to it
        would be wrong.
        """
        try:
            self._setup()
            # Drain any stale reply from a previous, timed-out attempt.
            while True:
                try:
                    self._sock.recvfrom(48)
                except OSError:
                    break
            pkt = bytearray(48)
            pkt[0] = 0x1B  # LI=0, VN=3, Mode=3 (client)
            _feed()
            t_send = time.ticks_ms()
            self._sock.sendto(pkt, self._addr)
            deadline = time.ticks_add(t_send, budget_ms)
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                try:
                    data, _ = self._sock.recvfrom(48)
                except OSError:  # EAGAIN: no reply yet
                    _feed()
                    time.sleep_ms(2)
                    continue
                t_recv = time.ticks_ms()
                if len(data) < 48:
                    continue
                # Transmit timestamp: 32-bit seconds + fraction, big endian.
                secs, frac = struct.unpack("!II", data[40:48])
                utc_ms = (secs - NTP_DELTA) * 1000 + (frac * 1000 >> 32)
                rtt = time.ticks_diff(t_recv, t_send)
                self._failures = 0
                return utc_ms, time.ticks_add(t_send, rtt // 2)
        except OSError as exc:
            print("NTP query error:", exc)
            self.close()
        self._note_failure()
        return None


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


def sync_clock(ntp, clock):
    """Sync `clock` from the NTP server, with retries.

    Used at start-up and after power-save wake-ups, where blocking for a
    few seconds is fine.  Returns True on success.
    """
    for attempt in range(config.NTP_RETRIES):
        res = ntp.query(config.NTP_TIMEOUT_S * 1000)
        if res:
            clock.set(*res)
            t = time.gmtime(res[0] // 1000
                            + config.TIME_OFFSET_HOURS * 3600)
            print("NTP sync OK: %04d-%02d-%02d %02d:%02d:%02d (local)"
                  % (t[0], t[1], t[2], t[3], t[4], t[5]))
            return True
        print("NTP attempt %d/%d failed"
              % (attempt + 1, config.NTP_RETRIES))
        _feed()
        time.sleep_ms(1000)
    return False


# ---------------------------------------------------------------------------
# Power-save scheduling (battery operation)
# ---------------------------------------------------------------------------

def parse_windows(specs):
    """Parse ("HH:MM-HH:MM", ...) into (start, end) seconds-of-day pairs.

    A window whose end is not after its start crosses midnight
    (e.g. "23:45-00:15").
    """
    windows = []
    for spec in specs:
        try:
            start_str, end_str = spec.split("-")
            sh, sm = [int(x) for x in start_str.split(":")]
            eh, em = [int(x) for x in end_str.split(":")]
        except ValueError:
            raise ValueError("bad window %r, expected 'HH:MM-HH:MM'" % spec)
        if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
            raise ValueError("bad time of day in window %r" % spec)
        start, end = sh * 3600 + sm * 60, eh * 3600 + em * 60
        if start == end:
            raise ValueError("empty window %r" % spec)
        windows.append((start, end))
    if not windows:
        raise ValueError("POWER_SAVE_WINDOWS must not be empty")
    return windows


def window_remaining(windows, sec_of_day):
    """Seconds left in the window covering sec_of_day, or 0 if outside."""
    for start, end in windows:
        length = (end - start) % 86400
        elapsed = (sec_of_day - start) % 86400
        if elapsed < length:
            return length - elapsed
    return 0


def next_window_delta(windows, sec_of_day):
    """Seconds until the next window start (0 if one starts right now)."""
    return min((start - sec_of_day) % 86400 for start, _ in windows)


def wifi_off(wlan):
    """Shut the Wi-Fi chip down as far as the port allows."""
    try:
        wlan.disconnect()
    except OSError:
        pass
    wlan.active(False)
    try:
        wlan.deinit()
    except (AttributeError, OSError):
        pass


def power_nap(clock, ms):
    """Light-sleep for `ms` milliseconds, then re-anchor `clock`.

    Depending on the port/firmware version, time.ticks_ms() may or may
    not advance during machine.lightsleep(), so the clock is re-anchored
    from our own accounting of the slept time.  The residual error is
    the lightsleep timer tolerance; callers must re-sync via NTP before
    trusting the clock for transmission.
    """
    wake_utc = clock.now_ms() + ms
    remaining = ms
    while remaining > 0:
        chunk = min(remaining, 60000)
        machine.lightsleep(chunk)
        remaining -= chunk
    clock.set(wake_utc, time.ticks_ms())


# ---------------------------------------------------------------------------
# Main transmit loop
# ---------------------------------------------------------------------------

def main():
    global _wdt
    if config.JJY_FREQUENCY_KHZ not in (40, 60):
        raise ValueError("JJY_FREQUENCY_KHZ must be 40 or 60")

    power_save = getattr(config, "POWER_SAVE", False)
    if power_save and getattr(config, "WATCHDOG", False):
        raise ValueError("POWER_SAVE cannot be combined with WATCHDOG "
                         "(light sleep stops feeding the watchdog)")
    # Validate the schedule before doing anything slow.
    windows = parse_windows(config.POWER_SAVE_WINDOWS) if power_save else None

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

    ntp = NTPClient(config.NTP_SERVER)
    wlan = connect_wifi(led)
    if not sync_clock(ntp, clock):
        raise OSError("initial NTP sync failed")

    offset_ms = config.TIME_OFFSET_HOURS * 3600 * 1000
    resync_ms = config.NTP_RESYNC_MINUTES * 60 * 1000
    last_sync = clock.now_ms()

    def local_secs():
        """Local (JST) seconds since the port epoch."""
        return (clock.now_ms() + offset_ms) // 1000

    def transmit(until_lsec):
        """Run the transmit loop until local second `until_lsec`
        (forever if None)."""
        nonlocal wlan, last_sync
        print("Transmitting JJY on GPIO%d at %d kHz"
              % (config.ANTENNA_PIN, config.JJY_FREQUENCY_KHZ))
        frame = None
        wifi_kick = None  # ticks_ms of the last background reconnect
        # Index of the next local (JST) second to transmit.
        next_idx = local_secs() + 1

        while until_lsec is None or next_idx < until_lsec:
            sec = next_idx % 60
            if frame is None or sec == 0:
                tm = time.gmtime(next_idx)
                frame = build_frame(tm)
                if sec == 0:
                    print("Frame %02d:%02d (doy %d)" % (tm[3], tm[4], tm[7]))

            boundary = next_idx * 1000 - offset_ms  # UTC ms of second start
            if boundary - clock.now_ms() < -100:
                # We fell behind (e.g. a slow NTP re-sync or a backward
                # time step): realign to the next full second and rebuild.
                next_idx = local_secs() + 1
                frame = None
                continue

            wait_until(boundary)
            carrier(True)
            wait_until(boundary + SYMBOL_ON_MS[frame[sec]])
            carrier(False)

            # Re-sync housekeeping runs in the 0.8 s carrier-off tail
            # of marker seconds (9, 19, ... 59).  The NTP query budget
            # is 250 ms and Wi-Fi reconnects associate in the
            # background, so the next second's edge is never delayed:
            # the signal keeps running through re-syncs and outages.
            if sec % 10 == 9 and clock.now_ms() - last_sync >= resync_ms:
                if wlan.isconnected():
                    res = ntp.query(250)
                    if res:
                        clock.set(*res)
                        last_sync = clock.now_ms()
                        wifi_kick = None
                        print("NTP re-sync OK")
                    else:
                        # Free-run on the crystal and retry in ~1 min
                        # (keeps the query rate polite during outages).
                        last_sync += 60 * 1000
                elif (wifi_kick is None or
                      time.ticks_diff(time.ticks_ms(), wifi_kick) > 30000):
                    # Kick a non-blocking reconnect; the cyw43 driver
                    # associates in the background while we transmit.
                    print("Wi-Fi lost, reconnecting in background...")
                    try:
                        wlan.active(True)
                        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
                    except OSError as exc:
                        print("Reconnect failed:", exc)
                    wifi_kick = time.ticks_ms()

            next_idx += 1
        carrier(False)

    if not power_save:
        transmit(None)  # never returns
        return

    # --- Power-save scheduling -------------------------------------------
    # Transmit during the configured daily windows only; light-sleep with
    # Wi-Fi off in between and re-sync via NTP on every wake-up.

    def try_resync():
        """Reconnect Wi-Fi and re-sync the clock after a wake-up."""
        nonlocal wlan, last_sync
        try:
            wlan = connect_wifi(led)
        except OSError as exc:
            print("Wi-Fi reconnect failed:", exc)
            return False
        if sync_clock(ntp, clock):
            last_sync = clock.now_ms()
            return True
        return False

    # Wake this many seconds before a window opens, leaving time to
    # reconnect Wi-Fi and re-sync (also absorbs lightsleep timer drift).
    margin_s = 120

    startup_min = getattr(config, "POWER_SAVE_STARTUP_MINUTES", 20)
    if startup_min > 0:
        print("Initial run: transmitting for %d min" % startup_min)
        transmit(local_secs() + startup_min * 60)

    # True while the clock has been NTP-verified since the last sleep.
    synced = True
    while True:
        remaining = window_remaining(windows, local_secs() % 86400)
        if remaining > 0:
            if synced:
                print("Window open for %d s" % remaining)
                transmit(local_secs() + remaining)
            elif try_resync():
                synced = True
            else:
                # Never transmit on an unverified clock: a wrong time
                # signal is worse than none.  Retry while the window
                # lasts, then give up until the next one.
                time.sleep(30)
            continue

        delta = next_window_delta(windows, local_secs() % 86400)
        nap_s = delta - margin_s
        if nap_s > 60:
            t = time.gmtime(local_secs() + delta)
            print("Sleeping %d s until next window at %02d:%02d"
                  % (nap_s, t[3], t[4]))
            ntp.close()  # the socket does not survive the Wi-Fi teardown
            wifi_off(wlan)
            time.sleep_ms(200)  # let the console output drain
            power_nap(clock, nap_s * 1000)
            synced = try_resync()
        elif not synced:
            synced = try_resync()
            if not synced:
                time.sleep(30)
        else:
            # Inside the wake margin with a verified clock: idle briefly
            # until the window opens.
            time.sleep_ms(min(delta, 10) * 1000)


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
