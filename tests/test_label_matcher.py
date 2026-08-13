import base64
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


@unittest.skipUnless(cv2 is not None, "opencv-python is not installed")
class LabelMatcherTests(unittest.TestCase):
    def encode(self, image):
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        return base64.b64encode(encoded.tobytes()).decode("ascii")

    def test_method14_preserves_alpha_and_self_matches(self):
        from easycon.label_matcher import match_prepared_label, prepare_label

        template = np.zeros((4, 4, 4), dtype=np.uint8)
        template[:, :, :3] = (20, 80, 140)
        template[:, :, 3] = np.array([
            [1, 64, 128, 254],
            [1, 64, 128, 254],
            [1, 64, 128, 254],
            [1, 64, 128, 254],
        ], dtype=np.uint8)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[10:14, 20:24] = template[:, :, :3]
        prepared = prepare_label({
            "ImgBase64": self.encode(template),
            "RangeX": 20,
            "RangeY": 10,
            "RangeWidth": 4,
            "RangeHeight": 4,
            "searchMethod": 14,
        })
        self.assertEqual(prepared["mask"][0].tolist(), [1, 64, 128, 254])
        match = match_prepared_label(frame, prepared)
        self.assertGreaterEqual(match.easycon_degree, 99)

    def test_non_16_by_9_frame_is_rejected(self):
        from easycon.label_matcher import normalize_frame

        with self.assertRaisesRegex(ValueError, "16:9"):
            normalize_frame(np.zeros((600, 800, 3), dtype=np.uint8))

    def test_method14_requires_an_alpha_channel(self):
        from easycon.label_matcher import match_prepared_label, prepare_label

        prepared = prepare_label({
            "ImgBase64": self.encode(np.zeros((4, 4, 3), dtype=np.uint8)),
            "RangeX": 0,
            "RangeY": 0,
            "RangeWidth": 4,
            "RangeHeight": 4,
            "searchMethod": 14,
        })
        with self.assertRaisesRegex(ValueError, "Alpha"):
            match_prepared_label(np.zeros((1080, 1920, 3), dtype=np.uint8), prepared)


if __name__ == "__main__":
    unittest.main()
