from datetime import datetime, timedelta, timezone


def utcnow():
    """Naive UTC datetime. SQLite silently drops tzinfo on round-trip (a
    value written as timezone-aware comes back naive), so every timestamp in
    this app is kept naive UTC for consistency -- never mix with tz-aware
    datetimes when comparing two of them."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now():
    """Naive local wall-clock time — only for deciding what "today" is for the
    daily plan (the user studies in their local day, not UTC's)."""
    return datetime.now()


def local_today():
    return local_now().date()


def utc_offset():
    # Rounded to 15 min: the two clock reads above are microseconds apart.
    seconds = (local_now() - utcnow()).total_seconds()
    return timedelta(minutes=round(seconds / 900) * 15)


def start_of_today(now_utc=None):
    """Naive UTC timestamp of the start of the user's local day containing now_utc."""
    now_utc = now_utc or utcnow()
    offset = utc_offset()
    local = now_utc + offset
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight - offset


def start_of_local_day(day):
    """Naive UTC timestamp for local midnight of a given date."""
    return datetime(day.year, day.month, day.day) - utc_offset()


def to_local(dt_utc):
    if dt_utc is None:
        return None
    return dt_utc + utc_offset()
