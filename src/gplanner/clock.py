"""Server day, resets and local display times.

All date and time logic in the project lives here (DESIGN.md section 7).
Comparisons happen in UTC or server time; local time is for display only.
The server offset, reset hour and local zone come from ``Settings``.

Every method takes an optional ``now`` so callers and tests can pin the
instant. ``now`` must be timezone-aware.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from gplanner.config import Settings


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name} must be timezone-aware, got naive {dt!r}")


class Clock:
    def __init__(self, settings: Settings) -> None:
        self.server_tz = timezone(timedelta(hours=settings.server_utc_offset))
        self.local_tz = ZoneInfo(settings.local_tz)
        self.reset_hour = settings.reset_hour

    def _now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(UTC)
        _require_aware(now, "now")
        return now

    def server_day(self, now: datetime | None = None) -> date:
        """The game day: the date of (server time minus the reset hour)."""
        server_now = self._now(now).astimezone(self.server_tz)
        return (server_now - timedelta(hours=self.reset_hour)).date()

    def is_server_monday(self, now: datetime | None = None) -> bool:
        """True from Monday's reset until Tuesday's reset, in server time."""
        return self.server_day(now).weekday() == 0

    def next_reset_utc(self, now: datetime | None = None) -> datetime:
        """The next daily reset strictly after ``now``, in UTC."""
        server_now = self._now(now).astimezone(self.server_tz)
        reset = server_now.replace(hour=self.reset_hour, minute=0, second=0, microsecond=0)
        if reset <= server_now:
            # The server zone is a fixed offset, so adding a day is always 24 hours.
            reset += timedelta(days=1)
        return reset.astimezone(UTC)

    def next_reset_local(self, now: datetime | None = None) -> datetime:
        """The next daily reset strictly after ``now``, in the local display zone."""
        return self.to_local(self.next_reset_utc(now))

    def to_local(self, dt: datetime) -> datetime:
        """Convert an aware datetime to the local display zone."""
        _require_aware(dt, "dt")
        return dt.astimezone(self.local_tz)
