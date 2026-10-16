import unittest
from pathlib import Path

from travel_agents import load_hotels, select_hotel


class HotelTests(unittest.TestCase):
    def setUp(self):
        self.hotels = load_hotels(Path(__file__).with_name("hotels.json"))

    def test_selects_cheapest_matching_hotel_and_calculates_nights(self):
        hotel, total = select_hotel("Paris", 5, 1500, self.hotels)
        self.assertEqual(hotel["hotel_name"], "Demo Budget Hotel Paris")
        self.assertEqual(total, 320)

    def test_rejects_unknown_destination(self):
        with self.assertRaises(ValueError):
            select_hotel("Tokyo", 5, 1500, self.hotels)

    def test_rejects_hotel_cost_above_budget(self):
        with self.assertRaises(ValueError):
            select_hotel("Paris", 5, 300, self.hotels)


if __name__ == "__main__":
    unittest.main()
