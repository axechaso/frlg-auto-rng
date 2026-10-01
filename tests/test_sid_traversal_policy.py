import unittest

from automation.easycon118 import EasyCon118Options
from automation.planner import AutoSearchRequest
from automation.sid_traversal_policy import traversal_availability, validate_traversal_request


class SIDTraversalPolicyTests(unittest.TestCase):
    def test_wild_and_safe_static_routes_are_available(self):
        wild = traversal_availability(
            method="All Wild Methods", category="Grass", location="Viridian Forest",
            game="fr_nx", pokemon="Pikachu",
        )
        static = traversal_availability(
            method="Static 1", category="Stationary", location="Stationary",
            game="fr_nx", pokemon="Snorlax",
        )
        self.assertTrue(wild.supported, wild.reason)
        self.assertEqual(wild.encounter_kind, "wild")
        self.assertTrue(static.supported, static.reason)
        self.assertEqual(static.encounter_kind, "static")

    def test_tenlines_method_names_without_spaces_are_normalized(self):
        for method, category, location, pokemon, kind in (
            ("Static1", "Stationary", "Stationary", "Snorlax", "static"),
            ("Wild1", "Grass", "Viridian Forest", "Pikachu", "wild"),
        ):
            with self.subTest(method=method):
                result = traversal_availability(
                    method=method, category=category, location=location,
                    game="fr_nx", pokemon=pokemon,
                )
                self.assertTrue(result.supported, result.reason)
                self.assertEqual(result.encounter_kind, kind)

    def test_unproven_gift_route_and_conflicting_modes_are_rejected(self):
        gift = traversal_availability(
            method="Static 1", category="Gift", location="Gift", game="fr_nx", pokemon="Eevee",
        )
        self.assertFalse(gift.supported)
        self.assertIn("额外野生 Seed 复核", gift.reason)

        direct = traversal_availability(
            method="All Wild Methods", category="Grass", location="Viridian Forest",
            game="fr_nx", pokemon="Pikachu", direct_mode=True,
        )
        self.assertFalse(direct.supported)
        item = traversal_availability(
            method="All Wild Methods", category="Grass", location="Viridian Forest",
            game="fr_nx", pokemon="Pikachu", item_mode=True,
        )
        self.assertFalse(item.supported)

    def test_complete_request_policy_enforces_options_and_template(self):
        request = AutoSearchRequest(
            game="fr_nx", tid=12345, sid=54321, method="Static 1", category="Stationary",
            location="Stationary", pokemon="Snorlax", min_advances=1901, max_advances=3000,
        )
        options = EasyCon118Options(frame_parity_scheme=1, mystery_gift_enabled=False)
        route = validate_traversal_request(request, options, "NS火叶全自动一键乱数2.0.ecs")
        self.assertEqual(route.encounter_kind, "static")
        with self.assertRaisesRegex(ValueError, "正式版或时间轴版"):
            validate_traversal_request(request, options, "unknown.ecs")
        with self.assertRaisesRegex(ValueError, "礼物"):
            validate_traversal_request(
                AutoSearchRequest(
                    game="fr_nx", tid=12345, sid=54321, method="Static 1", category="Gift",
                    location="Gift", pokemon="Eevee", min_advances=1901, max_advances=3000,
                ), options, "NS火叶全自动一键乱数2.0.ecs",
            )


if __name__ == "__main__":
    unittest.main()
