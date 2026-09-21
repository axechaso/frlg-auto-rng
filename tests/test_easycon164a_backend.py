import unittest

import automation.easycon118 as backend


class EasyCon164aBackendTests(unittest.TestCase):
    def test_ocr_unavailable_sentinel_skips_name_correction(self):
        original = """\
FUNC OCR识别抓捕对象名称(): STRING
    $name = OCR(310, 141, 360, 53, "frlg_battle")
    $fixedName = OCR名称V2后处理($name)
    RETURN $fixedName
ENDFUNC

FUNC OCR最小3($A: INT, $B: INT, $C: INT): INT
    RETURN $A
ENDFUNC
"""
        configured = backend._apply_ocr_runtime_fallback_text(original)
        configured_again = backend._apply_ocr_runtime_fallback_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(backend.OCR_RUNTIME_FALLBACK_MARKER, configured)
        self.assertIn('IF $name == "OCR NOT SUPPORT"', configured)
        self.assertIn('IF $name == "OCR ARGS ERR!"', configured)
        self.assertLess(
            configured.index('IF $name == "OCR NOT SUPPORT"'),
            configured.index("$fixedName = OCR名称V2后处理($name)"),
        )


if __name__ == "__main__":
    unittest.main()
