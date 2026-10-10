from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

# =========================================================================== 1. schedule management
class Schedule:
    """A small calendar saved in a JSON file."""

    def __init__(self, path: str = "schedule.json"):
        self.path, self.events = path, {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.events = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.events = {}

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.events, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _span(date: str, time: str, minutes: int):
        start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        return start, start + timedelta(minutes=minutes)

    def _conflicts(self, date, time, minutes, ignore=None):
        start, end = self._span(date, time, minutes)
        hits = []
        for eid, ev in self.events.items():
            s, e = self._span(ev["date"], ev["time"], ev["duration_minutes"])
            if eid != ignore and start < e and s < end:  
                hits.append({"id": eid, **ev})
        return hits

    def run(self, action: str, event_name: str | None = None, date: str | None = None, time: str | None = None,
            duration_minutes: int | None = None, event_id: str | None = None, new_name: str | None = None,
            new_date: str | None = None, new_time: str | None = None, force: bool = False) -> dict[str, Any]:
        action = (action or "").lower().strip()
        if action not in ("create", "update", "delete", "list"):
            return {"status": "error", "message": f"Unknown action '{action}'. Use create, update, delete or list."}
        try:
            if action == "list":
                items = sorted(({"id": k, **v} for k, v in self.events.items() if not date or v["date"] == date),
                               key=lambda e: (e["date"], e["time"]))
                return {"status": "ok", "count": len(items), "events": items}
            if action == "create":
                return self._create(event_name, date, time, duration_minutes or 60, force)
            target = self._find(event_id, event_name, date)
            if isinstance(target, dict):
                return target
            if action == "delete":
                gone = self.events.pop(target)
                self._save()
                return {"status": "deleted", "message": f"Deleted '{gone['name']}' on {gone['date']} at {gone['time']}."}
            return self._update(target, new_name, new_date, new_time, duration_minutes, force)
        except ValueError:
            return {"status": "error", "message": "Invalid date or time. Use YYYY-MM-DD and 24-hour HH:MM."}

    def _create(self, name, date, time, minutes, force):
        if not (name and date and time):
            return {"status": "error", "message": "To create an event I need an event name, a date (YYYY-MM-DD) and a time (HH:MM)."}
        if minutes <= 0:
            return {"status": "error", "message": "duration_minutes must be positive."}
        clash = self._conflicts(date, time, minutes)
        if clash and not force:
            return {"status": "conflict", "message": f"'{name}' on {date} at {time} overlaps with {len(clash)} existing event(s). Nothing was saved. Pick another time, or confirm to book it anyway.", "conflicts": clash}
        eid = uuid.uuid4().hex[:8]
        self.events[eid] = {"name": name, "date": date, "time": time, "duration_minutes": minutes}
        self._save()
        res = {"status": "created", "message": f"Created '{name}' on {date} at {time} for {minutes} minutes.", "event": {"id": eid, **self.events[eid]}}
        if clash:
            res["warning"] = "Booked despite a conflict."
            res["conflicts"] = clash
        return res

    def _find(self, event_id, name, date):
        if event_id and event_id in self.events:
            return event_id
        if not name:
            return {"status": "error", "message": "Tell me which event (its name)."}
        found = [k for k, v in self.events.items() if v["name"].lower() == name.lower() and (not date or v["date"] == date)]
        if not found:
            return {"status": "not_found", "message": f"No event named '{name}'" + (f" on {date}." if date else ".")}
        if len(found) > 1:
            return {"status": "ambiguous", "message": "Several events match; give the date as well.", "matches": [{"id": k, **self.events[k]} for k in found]}
        return found[0]

    def _update(self, eid, new_name, new_date, new_time, minutes, force):
        ev = dict(self.events[eid])
        ev.update(name=new_name or ev["name"], date=new_date or ev["date"], time=new_time or ev["time"],
                  duration_minutes=minutes or ev["duration_minutes"])
        clash = self._conflicts(ev["date"], ev["time"], ev["duration_minutes"], ignore=eid)
        if clash and not force:
            return {"status": "conflict", "message": "That change would overlap with another event. Nothing was changed.", "conflicts": clash}
        self.events[eid] = ev
        self._save()
        return {"status": "updated", "message": f"Updated: '{ev['name']}' is now on {ev['date']} at {ev['time']}.", "event": {"id": eid, **ev}}


# =========================================================================== 2. location info
_CITIES = {  # city or country -> (country, IANA time zone)
    "cairo": ("Egypt", "Africa/Cairo"), "alexandria": ("Egypt", "Africa/Cairo"), "egypt": ("Egypt", "Africa/Cairo"),
    "riyadh": ("Saudi Arabia", "Asia/Riyadh"), "jeddah": ("Saudi Arabia", "Asia/Riyadh"),
    "dubai": ("United Arab Emirates", "Asia/Dubai"), "abu dhabi": ("United Arab Emirates", "Asia/Dubai"),
    "doha": ("Qatar", "Asia/Qatar"), "kuwait city": ("Kuwait", "Asia/Kuwait"), "amman": ("Jordan", "Asia/Amman"),
    "beirut": ("Lebanon", "Asia/Beirut"), "baghdad": ("Iraq", "Asia/Baghdad"), "istanbul": ("Turkey", "Europe/Istanbul"),
    "ankara": ("Turkey", "Europe/Istanbul"), "tehran": ("Iran", "Asia/Tehran"),
    "casablanca": ("Morocco", "Africa/Casablanca"), "tunis": ("Tunisia", "Africa/Tunis"), "algiers": ("Algeria", "Africa/Algiers"),
    "nairobi": ("Kenya", "Africa/Nairobi"), "lagos": ("Nigeria", "Africa/Lagos"),
    "johannesburg": ("South Africa", "Africa/Johannesburg"), "cape town": ("South Africa", "Africa/Johannesburg"),
    "london": ("United Kingdom", "Europe/London"), "paris": ("France", "Europe/Paris"), "berlin": ("Germany", "Europe/Berlin"),
    "madrid": ("Spain", "Europe/Madrid"), "rome": ("Italy", "Europe/Rome"), "amsterdam": ("Netherlands", "Europe/Amsterdam"),
    "moscow": ("Russia", "Europe/Moscow"), "athens": ("Greece", "Europe/Athens"), "stockholm": ("Sweden", "Europe/Stockholm"),
    "zurich": ("Switzerland", "Europe/Zurich"), "new york": ("United States", "America/New_York"),
    "washington": ("United States", "America/New_York"), "chicago": ("United States", "America/Chicago"),
    "denver": ("United States", "America/Denver"), "los angeles": ("United States", "America/Los_Angeles"),
    "san francisco": ("United States", "America/Los_Angeles"), "seattle": ("United States", "America/Los_Angeles"),
    "toronto": ("Canada", "America/Toronto"), "vancouver": ("Canada", "America/Vancouver"),
    "mexico city": ("Mexico", "America/Mexico_City"), "sao paulo": ("Brazil", "America/Sao_Paulo"),
    "buenos aires": ("Argentina", "America/Argentina/Buenos_Aires"), "tokyo": ("Japan", "Asia/Tokyo"),
    "seoul": ("South Korea", "Asia/Seoul"), "beijing": ("China", "Asia/Shanghai"), "shanghai": ("China", "Asia/Shanghai"),
    "hong kong": ("China (Hong Kong SAR)", "Asia/Hong_Kong"), "singapore": ("Singapore", "Asia/Singapore"),
    "bangkok": ("Thailand", "Asia/Bangkok"), "jakarta": ("Indonesia", "Asia/Jakarta"), "mumbai": ("India", "Asia/Kolkata"),
    "delhi": ("India", "Asia/Kolkata"), "new delhi": ("India", "Asia/Kolkata"), "karachi": ("Pakistan", "Asia/Karachi"),
    "dhaka": ("Bangladesh", "Asia/Dhaka"), "sydney": ("Australia", "Australia/Sydney"),
    "melbourne": ("Australia", "Australia/Melbourne"), "auckland": ("New Zealand", "Pacific/Auckland"),
}


def location_info(location: str) -> dict[str, Any]:
    if not isinstance(location, str) or not location.strip():
        return {"status": "error", "message": "Please give a location name."}
    parts = [p.strip().lower() for p in location.split(",") if p.strip()]
    if not parts:
        return {"status": "error", "message": "Please give a location name."}
    key, qualifiers = parts[0], parts[1:]  # "Paris, France" -> key "paris", qualifier "france"
    country = tz = None
    if key in _CITIES and all(q in _CITIES[key][0].lower() for q in qualifiers):
        country, tz = _CITIES[key]
    elif not qualifiers:  # fall back to any IANA zone named after the city, e.g. "Reykjavik"
        wanted = key.replace(" ", "_")
        tz = next((z for z in sorted(available_timezones()) if z.split("/")[-1].lower() == wanted), None)
        country = "Unknown (not in the built-in table)" if tz else None
    if not tz:
        return {"status": "not_found", "message": f"I don't know the location '{location}'. Try a major city or country name."}
    now = datetime.now(ZoneInfo(tz))
    return {"status": "ok", "location": location.strip(), "country": country, "time_zone": tz,
            "utc_offset": now.strftime("%z"), "current_local_time": now.strftime("%Y-%m-%d %H:%M:%S")}


# =========================================================================== 3. analytics
def analytics(values: Any) -> dict[str, Any]:
    if not isinstance(values, (list, tuple)) or not values:
        return {"status": "error", "message": "Please give a non-empty list of numbers."}
    nums, ignored = [], []
    for v in values:
        try:
            if isinstance(v, bool):
                raise ValueError
            nums.append(float(str(v).replace(",", "").strip()) if not isinstance(v, (int, float)) else float(v))
        except (ValueError, TypeError):
            ignored.append(v)
    if not nums:
        return {"status": "error", "message": "None of the values are valid numbers.", "ignored": ignored}
    res = {"status": "ok", "count": len(nums), "average": round(sum(nums) / len(nums), 6), "maximum": max(nums), "minimum": min(nums)}
    if ignored:
        res["ignored_invalid_values"] = ignored
    return res


# =========================================================================== schemas (Ollama / OpenAI tool format)
def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties, "required": required}}}


_S = {"type": "string"}
TOOL_SCHEMAS = [
    _tool("schedule_manager",
          "Create, update, delete or list calendar events and detect scheduling conflicts. "
          "Dates are YYYY-MM-DD and times are 24-hour HH:MM. To update, give the event's current name (and date if "
          "needed) plus the new_* values.",
          {"action": {"type": "string", "enum": ["create", "update", "delete", "list"]},
           "event_name": _S, "date": {"type": "string", "description": "YYYY-MM-DD"},
           "time": {"type": "string", "description": "HH:MM, 24-hour"},
           "duration_minutes": {"type": "integer", "description": "default 60"},
           "new_name": _S, "new_date": _S, "new_time": _S,
           "force": {"type": "boolean", "description": "true only if the user explicitly says to book despite a conflict"}},
          ["action"]),
    _tool("location_info", "Get the country, time zone and current local time for a city or country.",
          {"location": _S}, ["location"]),
    _tool("analytics", "Compute count, average, maximum and minimum of a list of numbers.",
          {"values": {"type": "array", "items": {"type": "number"}, "description": "the numbers"}}, ["values"]),
]
