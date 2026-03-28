"""
Weather forecast module using Open-Meteo API (free, no API key required).

Fetches hourly shortwave radiation and cloud cover forecasts to enable
predictive sunset charging. When the forecast shows reduced afternoon solar,
the sunset algorithm can front-load charging in the morning.
"""
from __future__ import annotations
import json
import math
import ssl
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError


@dataclass
class HourlyForecast:
    """Single hour of forecast data."""
    hour_utc: datetime
    shortwave_radiation: float  # W/m² (direct + diffuse on horizontal surface)
    cloud_cover: float  # 0-100 %
    shortwave_radiation_clear_sky: float = 0.0  # W/m² theoretical max (no clouds)


@dataclass
class WeatherForecast:
    """
    Fetches and caches hourly solar radiation forecast from Open-Meteo.

    Uses shortwave_radiation (W/m²) as the primary metric — this is the total
    solar radiation reaching the ground and directly correlates with PV output.
    The forecast naturally accounts for clouds, aerosols, and sun angle.
    """
    latitude: float = 0.0
    longitude: float = 0.0
    refresh_hours: float = 1.0

    _hourly: list[HourlyForecast] = field(default_factory=list, repr=False)
    _last_fetch: float = 0.0
    _last_attempt: float = 0.0
    _consecutive_failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _fetch_error: str = ""

    @property
    def is_available(self) -> bool:
        return len(self._hourly) > 0

    @property
    def last_refresh(self) -> float:
        return self._last_fetch

    @property
    def fetch_error(self) -> str:
        return self._fetch_error

    def needs_refresh(self) -> bool:
        if not self._hourly:
            # Back off on repeated failures: 1m, 2m, 4m, 8m ... capped at 30m
            if self._consecutive_failures > 0:
                backoff_sec = min(60 * (2 ** (self._consecutive_failures - 1)), 1800)
                if time.time() - self._last_attempt < backoff_sec:
                    return False
            return True
        age_hours = (time.time() - self._last_fetch) / 3600.0
        return age_hours >= self.refresh_hours

    def fetch(self) -> bool:
        """
        Fetch today's hourly forecast from Open-Meteo.
        Returns True on success, False on failure.
        Tries HTTPS first, falls back to plain HTTP on SSL errors.
        Thread-safe; can be called from background thread.
        """
        params = (
            f"?latitude={self.latitude:.4f}"
            f"&longitude={self.longitude:.4f}"
            f"&hourly=shortwave_radiation,cloud_cover"
            f"&models=icon_eu"
            f"&forecast_days=1"
            f"&timezone=UTC"
        )
        self._last_attempt = time.time()

        urls = [
            f"https://api.open-meteo.com/v1/forecast{params}",
            f"http://api.open-meteo.com/v1/forecast{params}",
        ]
        last_err = ""
        for url in urls:
            try:
                req = Request(url, headers={"User-Agent": "DeyeMonitor/1.0"})
                kwargs: dict = {"timeout": 30}
                if url.startswith("https"):
                    kwargs["context"] = ssl.create_default_context()
                with urlopen(req, **kwargs) as resp:
                    data = json.loads(resp.read().decode())
                break
            except (URLError, OSError) as e:
                last_err = str(e)
                continue
        else:
            # Both URLs failed
            self._fetch_error = last_err
            self._consecutive_failures += 1
            return False

        try:
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            radiation = hourly.get("shortwave_radiation", [])
            cloud = hourly.get("cloud_cover", [])

            if not times or len(times) != len(radiation):
                self._fetch_error = "Incomplete forecast data"
                return False

            entries = []
            for i, t_str in enumerate(times):
                dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                cs_ghi = self._clear_sky_ghi(
                    dt - timedelta(minutes=30),  # API value = preceding hour mean
                    self.latitude, self.longitude,
                )
                entries.append(HourlyForecast(
                    hour_utc=dt,
                    shortwave_radiation=radiation[i] if radiation[i] is not None else 0.0,
                    cloud_cover=cloud[i] if i < len(cloud) and cloud[i] is not None else 0.0,
                    shortwave_radiation_clear_sky=cs_ghi,
                ))

            with self._lock:
                self._hourly = entries
                self._last_fetch = time.time()
                self._fetch_error = ""
                self._consecutive_failures = 0

            return True

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._fetch_error = str(e)
            self._consecutive_failures += 1
            return False

    def get_radiation_at(self, dt_utc: datetime) -> float | None:
        """Get forecast shortwave radiation (W/m²) for the hour containing dt_utc."""
        with self._lock:
            for entry in self._hourly:
                if entry.hour_utc <= dt_utc < entry.hour_utc + timedelta(hours=1):
                    return entry.shortwave_radiation
        return None

    def get_cloud_cover_at(self, dt_utc: datetime) -> float | None:
        """Get forecast cloud cover (%) for the hour containing dt_utc."""
        with self._lock:
            for entry in self._hourly:
                if entry.hour_utc <= dt_utc < entry.hour_utc + timedelta(hours=1):
                    return entry.cloud_cover
        return None

    def get_clear_sky_at(self, dt_utc: datetime) -> float:
        """Get computed clear-sky GHI (W/m²) for any time. No lock needed — pure math."""
        return self._clear_sky_ghi(dt_utc, self.latitude, self.longitude)

    def get_solar_weights(
        self, sunrise_utc: datetime, deadline_utc: datetime, steps: int = 24
    ) -> list[float]:
        """
        Build normalised solar weight curve from forecast radiation.

        Returns a list of `steps` weights (0.0–1.0) distributed evenly from
        sunrise_utc to deadline_utc. Each weight is the forecast
        shortwave_radiation at that moment normalised to the day's peak.

        If forecast data is unavailable for any slot, returns an empty list
        (caller should fall back to the theoretical cos² curve).
        """
        with self._lock:
            if not self._hourly:
                return []

            span = (deadline_utc - sunrise_utc).total_seconds()
            if span <= 0:
                return []

            dt_step = span / steps
            weights: list[float] = []
            for i in range(steps):
                t = sunrise_utc + timedelta(seconds=(i + 0.5) * dt_step)
                rad = None
                for entry in self._hourly:
                    if entry.hour_utc <= t < entry.hour_utc + timedelta(hours=1):
                        rad = entry.shortwave_radiation
                        break
                if rad is None:
                    return []  # Gap in data — fall back
                weights.append(max(rad, 0.0))

            peak = max(weights) if weights else 1.0
            if peak <= 0:
                return []
            return [w / peak for w in weights]

    def get_day_solar_quality(
        self, now_utc: datetime, deadline_utc: datetime
    ) -> float | None:
        """
        Ratio of forecast radiation to clear-sky radiation from now to deadline.

        Returns 0.0–1.0 where 1.0 = perfect clear sky, 0.0 = fully overcast.
        Returns None if clear-sky data is unavailable.

        Used to decide charging strategy:
        - High quality (clear day): follow solar curve, keep battery room for
          midday clipping when production exceeds grid export.
        - Low quality (cloudy day): flatten charging curve, front-load because
          there won't be midday surplus to capture.
        """
        with self._lock:
            if not self._hourly:
                return None

            total_forecast = 0.0
            total_clear_sky = 0.0
            for entry in self._hourly:
                if entry.hour_utc >= now_utc and entry.hour_utc < deadline_utc:
                    total_forecast += max(entry.shortwave_radiation, 0.0)
                    total_clear_sky += max(entry.shortwave_radiation_clear_sky, 0.0)

            if total_clear_sky <= 0:
                return None
            return min(1.0, total_forecast / total_clear_sky)

    def get_remaining_budget_ratio(
        self, now_utc: datetime, deadline_utc: datetime
    ) -> float | None:
        """
        Fraction of today's total solar radiation that remains between now and deadline.

        Returns 0.0–1.0, or None if forecast unavailable.
        Useful for quick "how much sun is left" check.
        """
        with self._lock:
            if not self._hourly:
                return None

            total = 0.0
            remaining = 0.0
            for entry in self._hourly:
                if entry.shortwave_radiation > 0:
                    total += entry.shortwave_radiation
                    if entry.hour_utc >= now_utc and entry.hour_utc < deadline_utc:
                        remaining += entry.shortwave_radiation

            if total <= 0:
                return None
            return remaining / total

    def summary_str(self) -> str:
        """One-line status string for the UI."""
        if not self.is_available:
            if self._fetch_error:
                err = self._fetch_error
                if self._consecutive_failures > 0 and self._last_attempt > 0:
                    backoff_sec = min(60 * (2 ** (self._consecutive_failures - 1)), 1800)
                    remaining = max(0, backoff_sec - (time.time() - self._last_attempt))
                    retry_str = f"retry in {remaining:.0f}s" if remaining > 0 else "retrying..."
                else:
                    retry_str = "retrying..."
                if "ssl" in err.lower() or "handshake" in err.lower():
                    return f"\u2601 SSL timeout — {retry_str}"
                if "timeout" in err.lower() or "timed out" in err.lower():
                    return f"\u2601 timeout — {retry_str}"
                return f"\u2601 error — {retry_str}"
            return "\u2601 fetching..."
        age_min = (time.time() - self._last_fetch) / 60.0
        now = datetime.now(timezone.utc)
        rad = self.get_radiation_at(now)
        cloud = self.get_cloud_cover_at(now)
        parts = [f"\u2600 {age_min:.0f}m ago"]
        if rad is not None:
            parts.append(f"{rad:.0f}W/m\u00b2")
        if cloud is not None:
            parts.append(f"\u2601{cloud:.0f}%")
        return " | ".join(parts)

    def day_sparkline(self, start_local_hour: int = 6, end_local_hour: int = 22) -> str:
        """
        Build a compact forecast strip showing hourly weather from start to end hour (local time).

        Uses weather icons based on cloud cover and radiation:
          ☀️ = clear sky (cloud < 20%)
          🌤️ = mostly sunny (cloud 20-40%)
          ⛅ = partly cloudy (cloud 40-70%)
          🌥️ = mostly cloudy (cloud 70-90%)
          ☁️ = overcast (cloud > 90%)
          🌙 = night (radiation ≈ 0 and outside solar hours)

        The current hour is marked with brackets, e.g. [12☀]

        Returns empty string if forecast unavailable.
        """
        with self._lock:
            if not self._hourly:
                return ""

            # Build mapping: local_hour -> (radiation, clear_sky_radiation)
            hour_data: dict[int, tuple[float, float]] = {}
            for entry in self._hourly:
                local_dt = entry.hour_utc.astimezone()
                h = local_dt.hour
                if start_local_hour <= h <= end_local_hour:
                    hour_data[h] = (entry.shortwave_radiation, entry.shortwave_radiation_clear_sky)

            if not hour_data:
                return ""

            now_local_hour = datetime.now().astimezone().hour

            parts: list[str] = []
            for h in range(start_local_hour, end_local_hour + 1):
                rad, clear_sky_rad = hour_data.get(h, (0.0, 0.0))
                icon = self._weather_icon(rad, clear_sky_rad)
                label = f"{h:02d}"
                if h == now_local_hour:
                    parts.append(f"[{label}{icon}]")
                else:
                    parts.append(f"{label}{icon}")

            return " ".join(parts)

    @staticmethod
    def _clear_sky_ghi(dt_utc: datetime, latitude: float, longitude: float) -> float:
        """
        Compute theoretical clear-sky Global Horizontal Irradiance (W/m²).

        Uses the Haurwitz (1945) model: GHI = 1098 × sin(α) × exp(-0.057 / sin(α))
        where α is the solar altitude angle. Simple, no dependencies, accurate
        enough for ratio-based comparisons (actual / clear_sky).
        """
        # Day of year
        doy = dt_utc.timetuple().tm_yday

        # Solar declination (Spencer, 1971)
        B = 2 * math.pi * (doy - 1) / 365.0
        decl = (0.006918 - 0.399912 * math.cos(B) + 0.070257 * math.sin(B)
                - 0.006758 * math.cos(2 * B) + 0.000907 * math.sin(2 * B)
                - 0.002697 * math.cos(3 * B) + 0.00148 * math.sin(3 * B))

        # Equation of time (minutes) — corrects for Earth's orbital eccentricity
        eot = (229.18 * (0.000075 + 0.001868 * math.cos(B)
               - 0.032077 * math.sin(B)
               - 0.014615 * math.cos(2 * B)
               - 0.04089 * math.sin(2 * B)))

        # True solar time
        utc_minutes = dt_utc.hour * 60.0 + dt_utc.minute
        solar_time_min = utc_minutes + eot + 4.0 * longitude  # 4 min per degree
        hour_angle = math.radians((solar_time_min / 4.0) - 180.0)  # 1° per 4 min

        # Solar altitude angle
        lat_rad = math.radians(latitude)
        sin_alt = (math.sin(lat_rad) * math.sin(decl)
                   + math.cos(lat_rad) * math.cos(decl) * math.cos(hour_angle))

        if sin_alt <= 0:
            return 0.0  # Sun below horizon

        # Haurwitz clear-sky model
        return 1098.0 * sin_alt * math.exp(-0.057 / sin_alt)

    @staticmethod
    def _weather_icon(radiation: float, clear_sky_radiation: float) -> str:
        """Pick a weather icon based on radiation ratio (actual / clear-sky max)."""
        if radiation < 10:
            return "\U0001F319"        # 🌙 night / no sun
        if clear_sky_radiation < 50:
            return "\U0001F319"        # 🌙 dawn/dusk (too low for meaningful ratio)
        ratio = radiation / clear_sky_radiation
        if ratio > 0.80:
            return "\u2600\uFE0F"      # ☀️ clear
        if ratio > 0.60:
            return "\U0001F324\uFE0F"  # 🌤️ mostly sunny
        if ratio > 0.40:
            return "\u26C5"            # ⛅ partly cloudy
        if ratio > 0.20:
            return "\U0001F325\uFE0F"  # 🌥️ mostly cloudy
        return "\u2601\uFE0F"          # ☁️ overcast
