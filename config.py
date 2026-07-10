# picojjy configuration.  Edit this file, then copy it to the Pico
# together with main.py.  See docs/INSTALL.md (Japanese) for details.

# --- Wi-Fi -----------------------------------------------------------------
WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-password"
# Seconds to wait for the Wi-Fi association before giving up.
WIFI_TIMEOUT_S = 30

# --- NTP -------------------------------------------------------------------
NTP_SERVER = "ntp.nict.jp"
# Re-synchronize with NTP every N minutes (keeps crystal drift bounded).
NTP_RESYNC_MINUTES = 60
# Timeout of a single NTP query, and how many times to retry it.
NTP_TIMEOUT_S = 5
NTP_RETRIES = 3

# --- JJY signal ------------------------------------------------------------
# Carrier frequency in kHz: 40 (Otakadoya-yama, eastern Japan) or
# 60 (Hagane-yama, western Japan).  Match what your clock expects;
# clocks with automatic selection accept either.
JJY_FREQUENCY_KHZ = 60
# GPIO number the antenna wire is connected to (through a resistor).
ANTENNA_PIN = 15
# PWM duty of the carrier while ON (0.0-1.0).  0.5 gives the cleanest
# square wave; lower it to reduce the radiated power.
CARRIER_DUTY = 0.5
# Offset from UTC in hours.  JJY carries JST, so keep 9 for real
# radio-controlled clocks sold for the Japanese market.
TIME_OFFSET_HOURS = 9

# --- Power save (battery operation) -----------------------------------------
# Transmit only during the daily windows below and light-sleep with
# Wi-Fi off in between (a few mA instead of ~70 mA).  The clock is
# re-synced via NTP on every wake-up.  Cannot be combined with WATCHDOG.
# The USB serial console stops during light sleep, so keep this False
# while developing.
POWER_SAVE = False
# Right after power-on, transmit continuously for this many minutes
# (time to place and force-sync your clocks) before the schedule starts.
POWER_SAVE_STARTUP_MINUTES = 20
# Daily transmit windows in local time, "HH:MM-HH:MM" each.  A window
# may cross midnight.  Most Japanese radio-controlled clocks attempt
# automatic reception around midnight and/or noon, so the defaults
# cover both.
POWER_SAVE_WINDOWS = ("11:45-12:15", "23:45-00:15")

# --- Misc ------------------------------------------------------------------
# Blink the onboard LED in sync with the transmitted symbols.
STATUS_LED = True
# Automatically reset the board 10 s after an unrecoverable error, so
# the transmitter recovers from e.g. a long network outage on its own.
RESET_ON_ERROR = True
# Enable the hardware watchdog (8 s timeout).  Recovers even from hard
# hangs that never raise an exception (e.g. a frozen Wi-Fi driver).
# CAUTION: once enabled it cannot be turned off until the next reset,
# so the board reboots ~8 s after you stop the program at the REPL --
# keep this False while developing, set True for unattended operation.
# Requires NTP_TIMEOUT_S <= 7.
WATCHDOG = False
