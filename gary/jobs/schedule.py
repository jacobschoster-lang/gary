"""Schedule guard for the daily post.

GitHub Actions cron runs in UTC and has no DST awareness. To post at exactly
08:00 America/New_York year-round, the workflow triggers at both 12:00 and
13:00 UTC and calls this guard, which only allows the run when it is currently
the target local hour in the target timezone.

CLI:
    python -m gary.jobs.schedule --check   # exit 0 if it's time to post, else 1
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/New_York"
DEFAULT_HOUR = 8


def should_run_now(
    now_utc: datetime | None = None,
    tz_name: str = DEFAULT_TZ,
    hour: int = DEFAULT_HOUR,
) -> bool:
    """Return True when the current local time in ``tz_name`` is ``hour``:00."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    local = now_utc.astimezone(ZoneInfo(tz_name))
    return local.hour == hour


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily-post schedule guard")
    parser.add_argument("--check", action="store_true", help="exit 0 if it's time to post")
    parser.add_argument("--tz", default=DEFAULT_TZ)
    parser.add_argument("--hour", type=int, default=DEFAULT_HOUR)
    args = parser.parse_args(argv)

    ok = should_run_now(tz_name=args.tz, hour=args.hour)
    local = datetime.now(timezone.utc).astimezone(ZoneInfo(args.tz))
    print(f"local time in {args.tz}: {local.isoformat()} -> run={ok}")
    if args.check:
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
