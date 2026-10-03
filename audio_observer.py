"""Experimental sound matching and observation logs, with no workflow actions."""

from __future__ import annotations

import hashlib
import math
import wave
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = 0.80
LOG_PREFIX = "[声音观察] "
TEMPLATE_NAME = "frlg-shiny-v1.wav"


def read_template(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as audio:
        if audio.getframerate() != SAMPLE_RATE or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("声音样本必须是 16 kHz 单声道 PCM16 WAV")
        if not 4000 <= audio.getnframes() <= SAMPLE_RATE * 3:
            raise ValueError("声音样本长度须为 0.25～3 秒")
        frames = audio.getnframes()
        data = audio.readframes(frames)
    if len(data) != frames * 2:
        raise ValueError("声音样本不完整")
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
    if float(np.sqrt(np.mean(samples * samples))) < 1e-5:
        raise ValueError("声音样本为空或音量过低")
    return samples


class PcmStream:
    """Decode arbitrary byte boundaries and resample continuously to 16 kHz."""

    FORMATS = {"int16": ("<i2", 32768), "int32": ("<i4", 2147483648), "uint8": ("u1", 128), "float32": ("<f4", 1)}

    def __init__(self, sample_rate: int, channels: int, sample_format: str):
        if not 8000 <= sample_rate <= 192000 or not 1 <= channels <= 8 or sample_format not in self.FORMATS:
            raise ValueError("不支持的音频输入格式")
        self.sample_rate, self.channels, self.sample_format = sample_rate, channels, sample_format
        self.dtype, self.scale = self.FORMATS[sample_format]
        self.frame_bytes = np.dtype(self.dtype).itemsize * channels
        self.kernel = None
        if sample_rate > SAMPLE_RATE:
            # Anti-alias before interpolation. Retain FIR history across reads.
            t = np.arange(63, dtype=np.float64) - 31
            cutoff = 0.45 * SAMPLE_RATE / sample_rate
            kernel = 2 * cutoff * np.sinc(2 * cutoff * t) * np.hanning(63)
            self.kernel = (kernel / kernel.sum()).astype(np.float32)
        self.reset()

    def reset(self):
        self.pending = b""
        self.history = np.zeros(62, dtype=np.float32)
        self.previous = None
        self.input_count = self.output_count = 0

    def feed(self, data: bytes) -> np.ndarray:
        data = self.pending + data
        size = len(data) // self.frame_bytes * self.frame_bytes
        self.pending = data[size:]
        if not size:
            return np.empty(0, dtype=np.float32)
        samples = np.frombuffer(data[:size], dtype=self.dtype).astype(np.float32)
        if self.sample_format == "uint8":
            samples -= 128
        samples /= self.scale
        if not np.isfinite(samples).all():
            raise ValueError("音频输入含无效采样值")
        samples = np.clip(samples.reshape(-1, self.channels).mean(axis=1), -1, 1)
        if self.kernel is not None:
            joined = np.concatenate((self.history, samples))
            samples = np.convolve(joined, self.kernel, mode="valid")
            self.history = joined[-62:]
        if self.sample_rate == SAMPLE_RATE:
            return samples
        start = self.input_count
        self.input_count += len(samples)
        joined = samples if self.previous is None else np.concatenate(([self.previous], samples))
        if self.previous is not None:
            start -= 1
        self.previous = samples[-1]
        last_output = (self.input_count - 1) * SAMPLE_RATE // self.sample_rate
        positions = np.arange(self.output_count, last_output + 1, dtype=np.float64) * self.sample_rate / SAMPLE_RATE - start
        self.output_count = last_output + 1
        return np.interp(positions, np.arange(len(joined)), joined).astype(np.float32)


@dataclass(frozen=True)
class SoundMatch:
    score: float
    start_seconds: float
    end_seconds: float
    rms_dbfs: float


class ShinySoundDetector:
    """Compare time-varying spectra; results are observations, not shiny verdicts.

    Per-frame and per-band centering reduces volume/static-background effects.
    A short peak window and cooldown collapse one sound into one observation.
    Scores are similarities to one recording, never calibrated probabilities.
    """

    FFT = 512
    HOP = 160
    PEAK_SECONDS = 0.15
    COOLDOWN_SECONDS = 3.0

    def __init__(self, template: np.ndarray, threshold: float = DEFAULT_THRESHOLD):
        if not math.isfinite(threshold) or not 0.5 <= threshold <= 0.99:
            raise ValueError("相似度阈值须在 0.50～0.99 之间")
        self.threshold = threshold
        self.window = np.hanning(self.FFT).astype(np.float32)
        frequencies = np.fft.rfftfreq(self.FFT, 1 / SAMPLE_RATE)
        edges = np.geomspace(700, 7600, 49)
        self.filters = np.array([
            ((frequencies >= low) & (frequencies < high)).astype(np.float32)
            for low, high in zip(edges[:-1], edges[1:])
        ])
        self.filters /= np.maximum(1, self.filters.sum(axis=1, keepdims=True))
        template = np.asarray(template, dtype=np.float32)
        if template.ndim != 1 or not np.isfinite(template).all() or not self.FFT * 2 <= len(template) <= SAMPLE_RATE * 3:
            raise ValueError("声音样本长度或内容无效")
        reference = np.array([self._feature(template[i:i + self.FFT]) for i in range(0, len(template) - self.FFT + 1, self.HOP)])
        self.reference = self._center(reference)
        self.reference_norm = float(np.linalg.norm(self.reference))
        if self.reference_norm < 1e-5:
            raise ValueError("声音样本缺少可用时序特征")
        self.frame_count = len(reference)
        self.reset()

    def reset(self):
        self.samples = np.empty(0, dtype=np.float32)
        self.features = deque(maxlen=self.frame_count)
        self.powers = deque(maxlen=self.frame_count)
        self.offset = 0
        self.peak = None
        self.peak_deadline = 0.0
        self.cooldown_until = 0.0

    def _feature(self, samples):
        power = np.abs(np.fft.rfft(samples * self.window)) ** 2
        return np.log(np.maximum(self.filters @ power, 1e-10)).astype(np.float32)

    @staticmethod
    def _center(features):
        value = features - features.mean(axis=1, keepdims=True)
        return value - value.mean(axis=0, keepdims=True)

    def feed(self, samples: np.ndarray) -> list[SoundMatch]:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not np.isfinite(samples).all() or len(samples) > SAMPLE_RATE:
            raise ValueError("音频块无效或超过一秒，需重置连续窗口")
        self.samples = np.concatenate((self.samples, samples))
        matches = []
        while len(self.samples) >= self.FFT:
            frame = self.samples[:self.FFT]
            self.features.append(self._feature(frame))
            self.powers.append(float(np.mean(frame * frame)))
            end = (self.offset + self.FFT) / SAMPLE_RATE
            self.samples = self.samples[self.HOP:]
            self.offset += self.HOP
            if len(self.features) != self.frame_count:
                continue
            rms_dbfs = 10 * math.log10(max(float(np.mean(self.powers)), 1e-12))
            if end >= self.cooldown_until and rms_dbfs >= -65:
                current = self._center(np.asarray(self.features))
                denominator = float(np.linalg.norm(current)) * self.reference_norm
                score = float(np.sum(current * self.reference) / denominator) if denominator > 1e-8 else 0.0
                score = max(0.0, min(1.0, score))
                if score >= self.threshold and (self.peak is None or score > self.peak.score):
                    if self.peak is None:
                        self.peak_deadline = end + self.PEAK_SECONDS
                    duration = ((self.frame_count - 1) * self.HOP + self.FFT) / SAMPLE_RATE
                    self.peak = SoundMatch(score, end - duration, end, rms_dbfs)
            if self.peak is not None and end >= self.peak_deadline:
                matches.append(self.peak)
                self.peak = None
                self.cooldown_until = end + self.COOLDOWN_SECONDS
        return matches


class ObservationLog:
    """Independent log file: workflow stdout/checkpoint files are never modified."""

    def __init__(self, user_root: Path):
        self.root = Path(user_root) / "logs" / "audio-observer"

    def append(self, message: str, *, now: datetime | None = None) -> str:
        now = now or datetime.now().astimezone()
        message = " ".join(str(message).split())
        line = f"{LOG_PREFIX}{now.isoformat(timespec='milliseconds')} {message}"
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"audio-observer-{now:%Y-%m-%d}.log"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        return line


def template_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
