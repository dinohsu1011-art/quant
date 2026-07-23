"""Print the most recent US trading session that should have settled data.

Weekday-only — market holidays are not modelled, so the day after a holiday
this returns the holiday itself and the refresh runs once, finds nothing new,
and leaves as_of behind. That costs ~9 wasted fetches a year, which is cheaper
than carrying an exchange calendar.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

now = datetime.now(ZoneInfo("America/New_York"))
d = now.date()
# today's close isn't dependable until well after the bell
if now.hour < 17:
    d -= timedelta(days=1)
while d.weekday() >= 5:  # Sat/Sun
    d -= timedelta(days=1)
print(d.isoformat())
