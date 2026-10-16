"""Multi-agent travel planner (local Ollama model + free real-data tools).
Setup:  ollama pull llama3.2   &&   pip install requests
Run:    python travel_agents.py
"""
import json, math, re, sys, requests
from datetime import datetime, date, timedelta
from pathlib import Path

MODEL, OLLAMA = "llama3.2", "http://localhost:11434"

def agent(role, task, js=False):
    """One specialized agent = one LLM call. js=True forces structured JSON output."""
    body = {"model": MODEL, "stream": False, "messages": [
        {"role": "system", "content": f"You are the {role}. Be concise and specific."},
        {"role": "user", "content": task}]}
    if js: body["format"] = "json"
    for _ in range(2):
        try:
            r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=300)
            if r.status_code == 404:
                sys.exit(f"Model '{MODEL}' not found. Run: ollama pull {MODEL}")
            r.raise_for_status()
            out = r.json()["message"]["content"]
        except requests.ConnectionError:
            sys.exit("Ollama is not running. Start it with: ollama serve")
        except requests.Timeout:
            sys.exit("Ollama request timed out. Try again.")
        except requests.RequestException as e:
            sys.exit(f"Ollama request failed: {e}")
        except (ValueError, KeyError, TypeError):
            sys.exit("Ollama returned an unexpected response.")
        if not js: return out
        try:
            res = json.loads(out)
            if isinstance(res, dict): return res
        except json.JSONDecodeError: pass          # retry once on bad / non-object JSON
    sys.exit("Model did not return valid JSON.")

def valid_places(d):
    ps = d.get("places")
    return isinstance(ps, list) and 1 <= len(ps) <= 15 and all(
        isinstance(p, dict) and all(isinstance(p.get(k), str) and p[k].strip() for k in ("name", "activity"))
        and type(p.get("est_cost_usd")) in (int, float) and 0 <= p["est_cost_usd"] <= 100_000 for p in ps)

def calculate_budget(budget, places, costs, accommodation_free=False):
    """Calculate trip costs and determine budget status in code."""
    required = ("accommodation", "food", "transport")
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or not 0 < budget < float("inf"):
        raise ValueError("Budget must be a positive, finite number.")
    if not all(
        isinstance(costs.get(k), (int, float))
        and not isinstance(costs.get(k), bool)
        and (costs[k] >= 0 if k == "accommodation" and accommodation_free else costs[k] > 0)
        and costs[k] < float("inf")
        for k in required
    ):
        raise ValueError("Budget costs must be positive; accommodation may be zero only when confirmed free.")
    for place in places["places"]:
        cost = place.get("est_cost_usd")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise ValueError(
                f"Invalid activity cost for {place.get('name', 'unknown place')}."
            )
    activities = sum(p["est_cost_usd"] for p in places["places"])
    breakdown = {k: costs[k] for k in required}
    breakdown["activities"] = activities
    total = sum(breakdown.values())
    if not total < float("inf"):
        raise ValueError("Total cost is not finite.")
    return breakdown, total, total <= budget

def valid_agent_costs(costs):
    """Validate the exact food and transport shape returned by Budget Agent."""
    return (
        isinstance(costs, dict)
        and set(costs) == {"food", "transport"}
        and all(
            type(costs.get(key)) in (int, float)
            and 0 < costs[key] <= 1e7
            and costs[key] < float("inf")
            for key in ("food", "transport")
        )
    )

def valid_itinerary(day_list, days):
    """Return whether an itinerary has exactly the requested numbered days."""
    return (
        isinstance(day_list, list)
        and len(day_list) == days
        and all(
            isinstance(day, dict)
            and isinstance(day.get("plan"), str)
            and day["plan"].strip()
            for day in day_list
        )
        and [day.get("day") for day in day_list] == list(range(1, days + 1))
    )

def load_hotels(path):
    """Load and validate the demo hotel data used for accommodation estimates."""
    try:
        with open(path, encoding="utf-8") as file:
            hotels = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load hotel data from {path}: {error}") from error
    if not isinstance(hotels, list) or not all(
        isinstance(hotel, dict)
        and isinstance(hotel.get("city"), str) and hotel["city"].strip()
        and isinstance(hotel.get("hotel_name"), str) and hotel["hotel_name"].strip()
        and type(hotel.get("price_per_night_usd")) in (int, float)
        and 0 < hotel["price_per_night_usd"] < float("inf")
        for hotel in hotels
    ):
        raise ValueError("Hotel data must contain valid city, hotel_name, and positive nightly prices.")
    return hotels

def select_hotel(destination, days, budget, hotels):
    """Select the cheapest matching hotel whose stay fits within the budget."""
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("Trip days must be a positive integer.")
    nights = max(days - 1, 1)
    matches = [hotel for hotel in hotels if hotel["city"].casefold() == destination.casefold()]
    if not matches:
        raise ValueError(f"No hotel data found for '{destination}'.")
    matches.sort(key=lambda hotel: hotel["price_per_night_usd"])
    hotel = next(
        (candidate for candidate in matches
         if candidate["price_per_night_usd"] * nights <= budget),
        None,
    )
    if hotel is None:
        raise ValueError(f"No hotel in '{destination}' fits the ${budget:.2f} budget.")
    return hotel, hotel["price_per_night_usd"] * nights

def get_places(task):
    for _ in range(2):                              # retry once, telling the agent what was wrong
        p = agent("Destination Agent", task, True)
        if valid_places(p): return p
        task += ("\nYour previous response was invalid. Return 1-15 places, each with non-empty string fields "
                 "'name' and 'activity', and a numeric 'est_cost_usd' between 0 and 100000.")
    sys.exit("Destination Agent returned invalid place data.")

def facts(dest, start, days):
    """Real-data tools (free, no key): Wikivoyage guide + Open-Meteo forecast for the TRIP dates."""
    guide, weather = "(guide unavailable)", "(weather unavailable)"
    guide_source, weather_source = "unavailable", "unavailable"
    try:
        r = requests.get(
            "https://en.wikivoyage.org/w/api.php",
            headers={"User-Agent": "TravelAgentsProject/1.0 (educational project; contact: rahmafathy550@gmail.com)"},
            params={
                "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                "titles": dest, "format": "json"},
            timeout=15)
        r.raise_for_status()
        guide = next(iter(r.json()["query"]["pages"].values())).get("extract", "")[:3000] or guide
        if guide != "(guide unavailable)":
            guide_source = "Wikivoyage"
    except Exception as e: print(f"Warning: guide unavailable ({e})")
    try:
        end = start + timedelta(days=days - 1)
        if end > date.today() + timedelta(days=15):
            weather = "Not available: trip is beyond the 16-day forecast window; say typical seasonal weather is unverified."
        else:
            r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": dest, "count": 1}, timeout=15)
            r.raise_for_status()
            res = r.json().get("results")
            if not res: raise ValueError(f"no location found for '{dest}'")
            g = res[0]
            print(f"Weather location matched: {g.get('name')}, {g.get('admin1', '')}, {g.get('country', '')}")
            r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
                "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto",
                "start_date": start.isoformat(), "end_date": end.isoformat(),
                "daily": "temperature_2m_max,precipitation_sum"})
            r.raise_for_status()
            daily = r.json().get("daily")
            weather = daily if daily and "time" in daily else "Forecast unavailable for the requested dates."
            if isinstance(weather, dict):
                weather_source = "Open-Meteo"
    except Exception as e: print(f"Warning: weather unavailable ({e})")
    return {"guide": guide, "weather": weather, "guide_source": guide_source, "weather_source": weather_source}

def ask(msg, cast, hi):
    while True:
        try:
            v = cast(input(msg))
            if 0 < v <= hi: return v          # also rejects inf / nan
        except ValueError: pass
        print(f"Please enter a positive number up to {hi:g}.")

def ask_date():
    while True:
        try:
            d = datetime.strptime(input("Start date (YYYY-MM-DD): "), "%Y-%m-%d").date()
            if d >= date.today(): return d
        except ValueError: pass
        print("Please enter a valid date that is today or later, e.g. 2026-11-05.")

def main():
    """Collect trip details, run the agents, and save the generated plan."""

    dest = input("Destination: ").strip() or sys.exit("Destination is required.")
    budget = ask("Total budget (USD): ", float, 1e7)
    while not (interests := input("Interests (comma-separated): ").strip()):
        print("Please enter at least one interest, e.g. museums, history, food.")
    days = ask("Number of days: ", int, 30)
    start = ask_date()
    hotel_data = load_hotels(Path(__file__).with_name("hotels.json"))
    hotel, accommodation_cost = select_hotel(dest, days, budget, hotel_data)
    info = (f"Destination: {dest}; Budget: ${budget:.0f}; Interests: {interests}; Days: {days}; "
            f"Hotel: {hotel['hotel_name']}; Accommodation: ${accommodation_cost:.0f}; "
            f"Start: {start}")
    data = facts(dest, start, days)
    
    places = get_places(f"{info}\nReal data:\n{data['guide']}\nSuggest places/activities matching the interests. "
                        'Return JSON: {"places":[{"name":"","activity":"","est_cost_usd":0}]}')
    
    # Budget agent + revision loop (max 2 revisions). Totals are computed and validated in code.
    feedback, keys, total = "", ("accommodation", "food", "transport", "activities"), float("inf")
    for attempt in range(3):
        costs = agent(
            "Budget Agent",
            f"{info}\n"
            f"Places:\n{json.dumps(places)}\n"
            f"{feedback}\n"
            "Return exactly one JSON object with exactly two keys: "
            '"food" and "transport". Both values must be positive JSON '
            "numbers representing the whole-trip totals in USD. "
            f"Accommodation is fixed at ${accommodation_cost:.2f}. "
            "Activities are calculated separately by the Python program. "
            "Do not include accommodation, activities, total_food, "
            'total_trip_cost_usd, or any additional keys. '
            'Example: {"food": 200, "transport": 80}',
            True,
        )
        vals = {
            "accommodation": accommodation_cost,
            "food": costs.get("food"),
            "transport": costs.get("transport"),
        }
        if not valid_agent_costs(costs):
            total = float("inf")
            feedback = (
                f"Invalid Budget Agent response: {json.dumps(costs)}. "
                'Return exactly {"food": 200, "transport": 80} '
                "with your own positive numeric estimates."
            )
            continue
        try:
            vals, total, within = calculate_budget(
                budget, places, vals)
        except ValueError as error:
            total, feedback = float("inf"), f"Your last budget was invalid: {error}"
            continue
        if within: break
        feedback = (f"Your previous total ${total:.2f} exceeded "
                    f"the budget ${budget:.2f}. Choose cheaper options.")
        if attempt < 2:
            places = get_places(f"{info}\nReplace expensive picks with cheaper ones.\nCurrent:\n{json.dumps(places)}\n"
                                'Return the same JSON format: {"places":[{"name":"","activity":"","est_cost_usd":0}]}')
    if total == float("inf"):
        sys.exit(
            "Budget calculation failed after 3 attempts.\n"
            f"Last error: {feedback}"
        )
    within = total <= budget
    
    # Itinerary + recommendations + evaluator loop (max 2 attempts); day count verified in code.
    issues, recs, itin_txt = "", "", ""
    verdict = {"verdict": "FAIL", "reason": "Itinerary day count never matched the requested days."}
    for attempt in range(2):
        itin = agent("Itinerary Agent", f"{info}\nPlaces:\n{json.dumps(places)}\nCosts:\n{json.dumps(vals)}\n"
                     f"Weather for the trip dates:\n{json.dumps(data['weather'])}\n{issues}\n"
                     f'Return JSON with exactly {days} days: {{"days":[{{"day":1,"plan":""}}]}}', True)
        day_list = itin.get("days")
        if not valid_itinerary(day_list, days):
            issues = f"Invalid itinerary: need exactly {days} entries numbered 1..{days}, each with a non-empty text 'plan'."
            continue
        itin_txt = "\n".join(f"Day {d.get('day')}: {d.get('plan')}" for d in day_list)
        recs = agent(
            "Recommendation Agent",
            f"{info}\n"
            f"Review and give final travel tips:\n{json.dumps(places)}\n"
            f"Verified budget breakdown:\n{json.dumps(vals)}\n"
            f"Verified total: ${total:.2f}\n"
            f"Budget limit: ${budget:.2f}\n"
            f"Budget status: {'WITHIN BUDGET' if within else 'OVER BUDGET'}\n"
            f"{itin_txt}\n"
            "Important rules:\n"
            "1. Do not change or recalculate the verified budget figures.\n"
            "2. Do not describe optional paid purchases as included in the plan.\n"
            "3. If suggesting a paid extra, label it OPTIONAL and state that "
            "its cost is not included in the verified total.\n"
            "4. Do not suggest expensive restaurants or activities as if they "
            "are covered unless their cost is included in the budget.\n"
            "5. Keep recommendations consistent with the stated interests.",
        )
        verdict = agent("Evaluator Agent", f"{info}\nVerified total: ${total:.2f}; code-verified budget status is {'PASS' if within else 'FAIL'}.\n"
                        f"Check consistency with interests, budget and days:\n{itin_txt}\n{recs}\n"
                        'Return JSON: {"verdict":"PASS or FAIL","reason":"specific explanation"}. '
                        f'The itinerary has already been checked to contain exactly {days} days. '
                        f'The requested interests are: {interests}. '
                        'Evaluate only whether the actual day-by-day itinerary meaningfully includes '
                        'activities related to each interest. For history, look for explicit '
                        'historical sites, museums, monuments, or historical context. '
                        'For food, look for food markets, local cuisine, or food experiences. '
                        'Do not require every day to match every interest. Do not fail a plan merely '
                        'because it omits other attractions. The code-verified budget status must not '
                        'be overridden; if it is FAIL, return FAIL. Give a specific, non-empty reason.', True)
        v = verdict.get("verdict")
        verdict["verdict"] = v.strip().upper() if isinstance(v, str) and v.strip().upper() in ("PASS", "FAIL") else "FAIL"
        reason = verdict.get("reason")
        verdict["reason"] = (
            reason.strip()
            if isinstance(reason, str) and reason.strip()
            else "Evaluator returned an empty reason."
        )
        if not within:
            verdict = {"verdict": "FAIL", "reason": f"Total cost ${total:.0f} exceeds the budget ${budget:.0f}."}
        if verdict["verdict"] == "PASS": break
        issues = f"The evaluator rejected your previous itinerary: {verdict.get('reason')}. Fix it."
    if not itin_txt:
        verdict = {
            "verdict": "FAIL",
            "reason": f"No valid {days}-day itinerary was produced after 2 attempts. {issues}",
        }
    status = "PASS" if within and verdict["verdict"] == "PASS" else "NEEDS_REVISION"
    
    plan = (f"TRAVEL PLAN [{status}] - {info}\n\n== Recommended Places & Activities ==\n"
            + "\n".join(f"- {p.get('name')}: {p.get('activity')} (~${p.get('est_cost_usd')})" for p in places.get("places", []))
            + "\n\n== Estimated Budget ==\n" + "\n".join(f"- {k}: ${vals[k]:.0f}" for k in keys)
            + f"\nTOTAL: ${total:.0f} / ${budget:.0f} -> "
            f"{'WITHIN budget' if within else 'OVER budget - draft is not executable'}"
            + f"\n\n== Day-by-Day Itinerary ==\n{itin_txt or '(no valid itinerary produced)'}\n\n== Final Recommendations ==\n{recs}"
            + f"\n\n== Evaluation ==\n{verdict.get('verdict')}: {verdict.get('reason')}\n"
            + f"\nNote: prices are model estimates; place info source: {data['guide_source']}; "
            f"weather source: {data['weather_source']}.\n")
    
    slug = re.sub(r"[^\w-]+", "_", dest).strip("_") or "trip"   # safe file name
    fname = f"travel_plan_{slug}_{datetime.now():%Y%m%d_%H%M}.txt"
    with open(fname, "w", encoding="utf-8") as f: f.write(plan)   # automation step
    print(plan + f"\n== Automated Action Result ==\nPlan ({status}) saved to {fname}")


if __name__ == "__main__":
    main()
