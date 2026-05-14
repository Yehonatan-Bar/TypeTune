import logging
import threading
from bisect import bisect_right
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from .models import AudioAnalysis, ImportedSong, SongBehavior

logger = logging.getLogger("typetune")

SAMPLE_RATE = 44100


class AudioPlaybackEngine:

    def __init__(self, volume: float = 0.35):
        self._lock = threading.Lock()
        self._audio_data: np.ndarray | None = None
        self._playhead_sample = 0
        self._total_samples = 0
        self._volume = volume

        self._should_play = False
        self._song_finished = False

        self._fade_volume = 0.0
        self._fade_target = 0.0
        self._fade_step = 0.0

        self._stream: sd.OutputStream | None = None

        self._bpm = 120.0
        self._beat_times: list[float] = []
        self._bar_times: list[float] = []
        self._behavior = SongBehavior()

        self._stop_at_sample: int | None = None

    def load_song(self, song: ImportedSong):
        self.stop()

        audio_path = song.normalized_audio_path
        if audio_path is None:
            logger.error("No normalized audio for %s", song.title)
            return

        data, sr = sf.read(str(audio_path), dtype="float32")
        if data.ndim == 1:
            data = np.column_stack([data, data])

        with self._lock:
            self._audio_data = data
            self._total_samples = len(data)
            self._playhead_sample = 0
            self._song_finished = False
            self._should_play = False
            self._fade_volume = 0.0
            self._fade_target = 0.0
            self._stop_at_sample = None

            if isinstance(song.analysis, AudioAnalysis):
                self._bpm = song.analysis.bpm
                self._beat_times = song.analysis.beat_times
                self._bar_times = song.analysis.bar_times
            else:
                self._bpm = song.bpm
                self._beat_times = []
                self._bar_times = []

            self._behavior = song.behavior

        fade_samples = int(SAMPLE_RATE * self._behavior.fade_ms / 1000)
        self._fade_step = 1.0 / max(fade_samples, 1)

        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=2,
            dtype="float32",
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()
        logger.info("Audio engine loaded: %s", song.title)

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status):
        with self._lock:
            if self._audio_data is None or self._song_finished:
                outdata[:] = 0
                return

            if not self._should_play and self._fade_volume <= 0.001:
                outdata[:] = 0
                return

            start = self._playhead_sample
            end = start + frames

            if self._stop_at_sample is not None and end > self._stop_at_sample:
                end = self._stop_at_sample

            if start >= self._total_samples:
                outdata[:] = 0
                self._song_finished = True
                return

            actual_end = min(end, self._total_samples)
            valid = actual_end - start

            if valid <= 0:
                outdata[:] = 0
                return

            chunk = self._audio_data[start:actual_end].copy()

            envelope = np.empty(valid, dtype=np.float32)
            vol = self._fade_volume
            for i in range(valid):
                if vol < self._fade_target:
                    vol = min(vol + self._fade_step, self._fade_target)
                elif vol > self._fade_target:
                    vol = max(vol - self._fade_step, self._fade_target)
                envelope[i] = vol
            self._fade_volume = vol

            chunk *= envelope[:, np.newaxis] * self._volume

            outdata[:valid] = chunk
            if valid < frames:
                outdata[valid:] = 0

            self._playhead_sample = actual_end

            if self._stop_at_sample is not None and actual_end >= self._stop_at_sample:
                self._should_play = False
                self._fade_target = 0.0
                self._stop_at_sample = None

            if actual_end >= self._total_samples:
                self._song_finished = True

    def tick(self, delta_seconds: float, credit_beats: float) -> float:
        with self._lock:
            if self._audio_data is None or self._song_finished:
                return 0.0

            current_time = self._playhead_sample / SAMPLE_RATE

            if credit_beats > 0:
                if not self._should_play:
                    self._should_play = True
                    self._fade_target = 1.0
                    self._stop_at_sample = None

                delta_beats = delta_seconds * self._bpm / 60.0
                consumed = min(delta_beats, credit_beats)
                return consumed

            else:
                if self._should_play and self._stop_at_sample is None:
                    boundary_time = self._find_next_boundary(current_time)
                    boundary_sample = int(boundary_time * SAMPLE_RATE)
                    fade_samples = int(SAMPLE_RATE * self._behavior.fade_ms / 1000)
                    self._stop_at_sample = min(
                        boundary_sample + fade_samples,
                        self._total_samples,
                    )
                    self._fade_target = 0.0

                return 0.0

    def _find_next_boundary(self, current_time: float) -> float:
        boundary = self._behavior.idle_stop_boundary
        if boundary == "soft":
            return current_time + 0.1

        times = self._beat_times if boundary == "beat" else self._bar_times
        if not times:
            return current_time + 0.1

        idx = bisect_right(times, current_time)
        if idx < len(times):
            return times[idx]
        return current_time + 0.1

    def is_finished(self) -> bool:
        with self._lock:
            return self._song_finished

    def get_playhead_seconds(self) -> float:
        with self._lock:
            return self._playhead_sample / SAMPLE_RATE

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            self._should_play = False
            self._audio_data = None
