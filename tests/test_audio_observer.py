import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from audio_observer import (
    LOG_PREFIX, ObservationLog, PcmStream, ShinySoundDetector, read_template,
)


TEMPLATE = Path(__file__).resolve().parents[1] / "assets/audio/frlg-shiny-v1.wav"


def detect(signal, *, size=733, threshold=0.8):
    detector = ShinySoundDetector(read_template(TEMPLATE), threshold)
    matches = []
    for offset in range(0, len(signal), size):
        matches.extend(detector.feed(signal[offset:offset + size]))
    return matches


class AudioObserverTests(unittest.TestCase):
    def test_sample_matches_with_volume_change_and_arbitrary_chunk_boundaries(self):
        template = read_template(TEMPLATE)
        for gain in (0.2, 1.0, -0.5):
            signal = np.concatenate((np.zeros(16000), template * gain, np.zeros(8000))).astype(np.float32)
            matches = detect(signal)
            self.assertEqual(len(matches), 1)
            self.assertGreater(matches[0].score, .99)
            self.assertAlmostEqual(matches[0].start_seconds, 1.0, places=2)

    def test_silence_noise_and_stationary_tone_do_not_match(self):
        t = np.arange(48000) / 16000
        negatives = (
            np.zeros(48000),
            np.random.default_rng(8).normal(0, .03, 48000),
            .1 * np.sin(2 * np.pi * 2000 * t),
        )
        for signal in negatives:
            self.assertEqual(detect(signal), [])

    def test_one_sound_is_deduplicated_and_later_sound_still_matches(self):
        template = read_template(TEMPLATE)
        signal = np.concatenate((np.zeros(1600), template, template, np.zeros(64000), template, np.zeros(8000)))
        self.assertEqual(len(detect(signal)), 2)

    def test_reset_does_not_join_sound_across_a_gap(self):
        template = read_template(TEMPLATE)
        detector = ShinySoundDetector(template)
        middle = len(template) // 2
        self.assertEqual(detector.feed(template[:middle]), [])
        detector.reset()
        self.assertEqual(detector.feed(np.concatenate((template[middle:], np.zeros(8000)))), [])

    def test_pcm_decoding_preserves_partial_frames_and_format_scaling(self):
        data = np.array([[0, 0], [32767, 32767], [-32768, -32768], [1000, -1000]], dtype="<i2").tobytes()
        decoder = PcmStream(16000, 2, "int16")
        samples = np.concatenate([decoder.feed(data[:3]), decoder.feed(data[3:9]), decoder.feed(data[9:])])
        np.testing.assert_allclose(samples, [0, 32767 / 32768, -1, 0])
        np.testing.assert_allclose(PcmStream(16000, 1, "uint8").feed(bytes([0, 128, 255])), [-1, 0, 127 / 128])
        values = np.array([-.5, .0, .25], dtype="<f4")
        np.testing.assert_allclose(PcmStream(16000, 1, "float32").feed(values.tobytes()), values)
        with self.assertRaises(ValueError):
            PcmStream(16000, 1, "float32").feed(np.array([np.nan], dtype="<f4").tobytes())

    def test_resampling_is_independent_of_packet_size(self):
        for rate in (44100, 48000):
            source = (.1 * np.sin(2 * np.pi * 1500 * np.arange(rate) / rate)).astype("<f4")
            payload = np.column_stack((source, source)).astype("<f4").tobytes()
            expected = PcmStream(rate, 2, "float32").feed(payload)
            decoder = PcmStream(rate, 2, "float32")
            actual = np.concatenate([decoder.feed(payload[i:i + 701]) for i in range(0, len(payload), 701)])
            self.assertEqual(len(actual), 16000)
            np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_48k_stereo_capture_can_match_resampled_reference(self):
        template = read_template(TEMPLATE)
        live = np.interp(np.arange(len(template) * 3) / 3, np.arange(len(template)), template)
        signal = np.concatenate((np.zeros(48000), live, np.zeros(24000))).astype("<f4")
        data = np.column_stack((signal, signal * .7)).astype("<f4").tobytes()
        decoder = PcmStream(48000, 2, "float32")
        samples = np.concatenate([decoder.feed(data[i:i + 7101]) for i in range(0, len(data), 7101)])
        matches = detect(samples)
        self.assertEqual(len(matches), 1)
        self.assertGreater(matches[0].score, .8)

    def test_observation_log_is_separate_single_line_and_discoverable(self):
        from pyside_app.log_history import discover_logs

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_log = root / "runtime/wild-existing.log"
            run_log.parent.mkdir()
            run_log.write_text("original output\n", encoding="utf-8")
            log = ObservationLog(root)
            line = log.append("疑似闪光音效\n音源=card", now=datetime(2026, 10, 2, tzinfo=timezone.utc))
            self.assertTrue(line.startswith(LOG_PREFIX))
            self.assertNotIn("\n", line)
            self.assertEqual(run_log.read_text(encoding="utf-8"), "original output\n")
            history = discover_logs(root / "runtime", root)
            self.assertTrue(any(entry.workflow == "声音观察" for entry in history))


if __name__ == "__main__":
    unittest.main()
