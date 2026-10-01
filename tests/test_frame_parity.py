import unittest

from automation.frame_parity import resolve_frame_parity


class FrameParityTests(unittest.TestCase):
    def test_requested_preference_survives_gift_forcing(self):
        result = resolve_frame_parity(
            requested=0, mystery_gift_enabled=True, is_egg=False
        )
        self.assertEqual((result.requested, result.effective), (0, 1))
        self.assertTrue(result.forced)
        restored = resolve_frame_parity(
            requested=result.requested, mystery_gift_enabled=False, is_egg=False
        )
        self.assertEqual(restored.effective, 0)

    def test_egg_uses_scheme_one_but_retains_request(self):
        result = resolve_frame_parity(
            requested=0, mystery_gift_enabled=False, is_egg=True
        )
        self.assertEqual((result.requested, result.effective), (0, 1))
        self.assertEqual(result.reason, "孵蛋流程固定使用方案 1")

    def test_invalid_values_are_not_hidden_by_forcing(self):
        with self.assertRaisesRegex(ValueError, "整数"):
            resolve_frame_parity(requested=True, mystery_gift_enabled=True, is_egg=False)
        with self.assertRaisesRegex(ValueError, "布尔值"):
            resolve_frame_parity(requested=0, mystery_gift_enabled=1, is_egg=False)


if __name__ == "__main__":
    unittest.main()
