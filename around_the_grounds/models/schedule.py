from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    venue_key: str
    venue_name: str
    title: str
    date: datetime
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    description: Optional[str] = None
    extraction_method: str = "html"
    # "event" is scheduled for `date`; "listing" is available now (e.g. a beer
    # on tap), is exempt from the upcoming-days window, and stays out of the
    # calendar feed.
    kind: str = "event"
    # For listings: which list the entry belongs to ("fresh-hop", "festbier",
    # "pumpkin").
    category: Optional[str] = None
    # The event's own page, when the source links one; templates fall back
    # to the venue URL.
    url: Optional[str] = None
    # Where the event is held, when that is not the source venue (a brewery's
    # list of events it pours at elsewhere).
    place: Optional[str] = None

    def __str__(self) -> str:
        date_str = self.date.strftime("%Y-%m-%d") if self.date else "None"
        time_str = ""
        if self.start_time:
            time_str = f" {self.start_time.strftime('%H:%M')}"
            if self.end_time:
                time_str += f"-{self.end_time.strftime('%H:%M')}"

        return f"{date_str}{time_str}: {self.title} @ {self.venue_name}"
