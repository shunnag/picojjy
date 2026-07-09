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

# --- Misc ------------------------------------------------------------------
# Blink the onboard LED in sync with the transmitted symbols.
STATUS_LED = True
# Automatically reset the board 10 s after an unrecoverable error, so
# the transmitter recovers from e.g. a long network outage on its own.
RESET_ON_ERROR = True
