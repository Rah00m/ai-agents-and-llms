import unittest

from travel_agents import calculate_budget, valid_agent_costs, valid_itinerary


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.places = {
            "places": [
                {"name": "Museum", "activity": "Art", "est_cost_usd": 18},
                {"name": "Tower", "activity": "Views", "est_cost_usd": 17},
                {"name": "Cruise", "activity": "River", "est_cost_usd": 15},
                {"name": "Gallery", "activity": "History", "est_cost_usd": 12},
            ]
        }
        self.costs = {
            "accommodation": 800,
            "food": 300,
            "transport": 100,
        }

    def test_budget_within_limit(self):
        breakdown, total, within = calculate_budget(1500, self.places, self.costs)
        self.assertEqual(breakdown["activities"], 62)
        self.assertEqual(total, 1262)
        self.assertTrue(within)

    def test_budget_exceeded(self):
        _, total, within = calculate_budget(1200, self.places, self.costs)
        self.assertEqual(total, 1262)
        self.assertFalse(within)

    def test_invalid_negative_cost(self):
        costs = dict(self.costs, food=-1)
        with self.assertRaises(ValueError):
            calculate_budget(1500, self.places, costs)

    def test_boolean_cost_is_rejected(self):
        costs = dict(self.costs, food=True)
        with self.assertRaises(ValueError):
            calculate_budget(1500, self.places, costs)

    def test_zero_accommodation_requires_confirmation(self):
        costs = dict(self.costs, accommodation=0)
        with self.assertRaises(ValueError):
            calculate_budget(1500, self.places, costs)

    def test_confirmed_free_accommodation_is_allowed(self):
        costs = dict(self.costs, accommodation=0)
        breakdown, total, within = calculate_budget(
            1500, self.places, costs, accommodation_free=True
        )
        self.assertEqual(breakdown["accommodation"], 0)
        self.assertEqual(total, 462)
        self.assertTrue(within)

    def test_fixed_hotel_cost_is_combined_with_agent_costs(self):
        agent_costs = {"food": 300, "transport": 100}
        vals = {
            "accommodation": 320,
            "food": agent_costs["food"],
            "transport": agent_costs["transport"],
        }
        breakdown, total, within = calculate_budget(1500, self.places, vals)
        self.assertEqual(breakdown["accommodation"], 320)
        self.assertEqual(total, 782)
        self.assertTrue(within)

    def test_budget_agent_requires_exact_food_and_transport_keys(self):
        self.assertTrue(valid_agent_costs({"food": 300, "transport": 100}))
        self.assertFalse(valid_agent_costs({
            "food": 300, "transport": 100, "total_food": 300,
        }))
        self.assertFalse(valid_agent_costs({
            "total_trip_cost_usd": 400, "accommodation": 320,
            "total_food": 300, "transport": 100,
        }))

    def test_budget_agent_rejects_non_positive_costs(self):
        self.assertFalse(valid_agent_costs({"food": 0, "transport": 100}))
        self.assertFalse(valid_agent_costs({"food": True, "transport": 100}))

    def test_itinerary_requires_exact_numbered_days(self):
        itinerary = [
            {"day": 1, "plan": "Museum"},
            {"day": 2, "plan": "Market"},
        ]
        self.assertTrue(valid_itinerary(itinerary, 2))
        self.assertFalse(valid_itinerary(itinerary, 3))
        self.assertFalse(valid_itinerary([{"day": 1, "plan": ""}], 1))

    def test_negative_activity_cost_is_rejected(self):
        places = {"places": [{"name": "Museum", "est_cost_usd": -50}]}
        costs = {"accommodation": 100, "food": 100, "transport": 50}
        with self.assertRaisesRegex(ValueError, "Invalid activity cost"):
            calculate_budget(500, places, costs)

    def test_non_finite_activity_cost_is_rejected(self):
        for invalid_cost in (float("nan"), float("inf"), True, "50"):
            with self.subTest(invalid_cost=invalid_cost):
                places = {"places": [{"name": "Museum", "est_cost_usd": invalid_cost}]}
                with self.assertRaises(ValueError):
                    calculate_budget(500, places, self.costs)

if __name__ == "__main__":
    unittest.main()
