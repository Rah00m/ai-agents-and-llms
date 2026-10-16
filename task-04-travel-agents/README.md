# Travel Agents

A multi-agent travel planner powered by a local Ollama language model. It combines destination recommendations, demo hotel data, budget validation, itinerary generation, travel tips, and plan evaluation.

## Features

- **Destination Agent:** Suggests places and activities based on the destination and the user's interests.
- **Budget Agent:** Estimates whole-trip food and transportation costs.
- **Hotel Selection:** Selects accommodation from local demo data in `hotels.json`.
- **Budget Validation:** Python validates costs, calculates the total trip budget, and checks whether it fits the user's budget.
- **Itinerary Agent:** Generates a day-by-day travel plan for the requested trip duration.
- **Recommendation Agent:** Provides travel tips while being instructed to preserve the verified budget figures.
- **Evaluator Agent:** Evaluates whether the itinerary meaningfully reflects the requested interests.
- **Optional Destination Data:** Retrieves destination guide information from Wikivoyage and weather forecasts from Open-Meteo when available.
- **Plan Export:** Saves the generated travel plan to a timestamped text file.

## How It Works

1. The program collects the destination, total budget in USD, interests, trip duration, and start date.
2. It loads demo hotel data from `hotels.json` and selects a hotel that fits the budget.
3. It attempts to retrieve destination information from Wikivoyage and weather forecasts from Open-Meteo. If external data is unavailable, the program can continue with fallback information.
4. The Destination Agent suggests places and activities with estimated costs.
5. The Budget Agent estimates food and transportation expenses. Python validates the returned costs and calculates the total, including accommodation and activities.
6. If the budget response is invalid, the program retries. If the estimated total exceeds the budget, it can request cheaper activity options.
7. The Itinerary Agent generates the daily plan. Python validates the number, order, and non-empty descriptions of the requested days.
8. The Recommendation Agent provides additional travel tips without being allowed to redefine the verified budget.
9. The Evaluator Agent checks whether the itinerary reflects the requested interests. The program can retry itinerary generation when validation or evaluation fails.
10. The final plan is marked `PASS` only when the estimated budget is within the limit and the Evaluator Agent returns `PASS`. Otherwise, the plan is marked `NEEDS_REVISION`.

## Requirements

- Python 3.10 or later
- [Ollama](https://ollama.com/)
- The `llama3.2` model
- Python package: `requests`

## Setup

Install the Python dependency:

```bash
python -m pip install requests
```

Download the Ollama model:

```bash
ollama pull llama3.2
```

Make sure Ollama is running and the model is available before starting the planner.

## Run

From the project directory, run:

```bash
python travel_agents.py
```

Follow the prompts to enter your trip details.

## Tests

Run the budget and hotel unit tests with:

```bash
python -m unittest -v test_budget.py test_hotels.py
```

These tests cover the budget and hotel-related functionality. They do not, by themselves, verify every agent or external API integration.

## Output

The program saves the generated travel plan to a timestamped text file in the project directory, using a filename similar to:

```text
travel_plan_paris_20261016_2353.txt
```

The report includes recommended places, the estimated budget breakdown, the day-by-day itinerary, final recommendations, evaluation results, and the data-source status.

## Limitations

- Hotel prices are demo data for testing and are not real booking prices.
- Activity, food, and transportation costs are estimates, not guaranteed prices.
- Weather forecasts are limited by Open-Meteo's available forecast window; longer-range weather information is not presented as a verified forecast.
- Wikivoyage and Open-Meteo depend on network availability and successful API responses.
- A `PASS` result indicates that the implemented budget and itinerary evaluation checks passed. It does not guarantee the accuracy of every travel recommendation or the completeness of all real-world trip expenses.
