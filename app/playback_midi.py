import logging
import math
import threading

import numpy as np
import sounddevice as sd

from .models import ImportedSong, MidiAnalysis, MidiNote, SongBehavior

logger = logging.getLogger("typetune")

SAMPLE_RATE = 44100


class MidiPlaybackEngine:

    def __init__(self, volume: float = 0.35):
        self._lock = threading.Lock()
        self._notes: list[MidiNote] = []
        self._bpm = 120.0
        self._volume = volume
        self._playhead_beat = 0.0
        self._total_beats = 0.0
        self._behavior = SongBehavior()
        self._song_finished = False
        self._should_play = False

        self._active_notes: dict[int, dict] = {}
        self._note_index = 0

        self._fade_volume = 0.0
        self._fade_target = 0.0
        self._fade_step = 0.0

        self._stream: sd.OutputStream | None = None
        self._playhead_lock_sample = 0.0

    def load_song(self, song: ImportedSong):
        self.stop()

        if not isinstance(song.analysis, MidiAnalysis):
            logger.error("Song %s has no MIDI analysis", song.title)
            return

        analysis = song.analysis

        with self._lock:
            self._notes = list(analysis.notes)
            self._bpm = analysis.bpm
            self._total_beats = song.duration_beats or (
                max((n.start_beat + n.duration_beats for n in self._notes), default=0)
            )
            self._playhead_beat = 0.0
            self._note_index = 0
            self._active_notes.clear()
            self._song_finished = False
            self._should_play = False
            self._fade_volume = 0.0
            self._fade_target = 0.0
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
        logger.info("MIDI engine loaded: %s (%.0f BPM, %d notes)", song.title, self._bpm, len(self._notes))

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status):
        with self._lock:
            if not self._active_notes or (not self._should_play and self._fade_volume <= 0.001):
                outdata[:] = 0
                return

            t = np.arange(frames, dtype=np.float64) / SAMPLE_RATE
            mixed = np.zeros(frames, dtype=np.float64)

            expired = []
            for pitch, info in self._active_notes.items():
                freq = info["freq"]
                phase = info["phase"]

                signal = np.sin(2 * math.pi * freq * t + phase)

                env = np.ones(frames, dtype=np.float64)
                attack = min(200, frames)
                if info["age_samples"] < attack:
                    start = info["age_samples"]
                    env_len = min(attack - start, frames)
                    env[:env_len] = np.linspace(start / attack, min((start + env_len) / attack, 1.0), env_len)

                remaining = info.get("remaining_samples", None)
                if remaining is not None and remaining < frames:
                    if remaining > 0:
                        release_len = remaining
                        env[-release_len:] *= np.linspace(1.0, 0.0, release_len)
                    else:
                        env[:] = 0
                    expired.append(pitch)

                vel_scale = info["velocity"] / 127.0 * 0.5
                mixed += signal * env * vel_scale

                info["phase"] = (phase + 2 * math.pi * freq * frames / SAMPLE_RATE) % (2 * math.pi)
                info["age_samples"] += frames
                if remaining is not None:
                    info["remaining_samples"] = max(0, remaining - frames)

            for p in expired:
                del self._active_notes[p]

            if np.max(np.abs(mixed)) > 1.0:
                mixed /= np.max(np.abs(mixed))

            envelope = np.empty(frames, dtype=np.float64)
            vol = self._fade_volume
            for i in range(frames):
                if vol < self._fade_target:
                    vol = min(vol + self._fade_step, self._fade_target)
                elif vol > self._fade_target:
                    vol = max(vol - self._fade_step, self._fade_target)
                envelope[i] = vol
            self._fade_volume = vol

            result = (mixed * envelope * self._volume).astype(np.float32)
            outdata[:, 0] = result
            outdata[:, 1] = result

    def tick(self, delta_seconds: float, credit_beats: float) -> float:
        with self._lock:
            if self._song_finished:
                return 0.0

            if credit_beats <= 0:
                if self._should_play:
                    self._should_play = False
                    self._fade_target = 0.0
                return 0.0

            if not self._should_play:
                self._should_play = True
                self._fade_target = 1.0

            delta_beats = delta_seconds * self._bpm / 60.0
            consumed = min(delta_beats, credit_beats)

            new_playhead = self._playhead_beat + consumed

            while self._note_index < len(self._notes):
                note = self._notes[self._note_index]
                if note.start_beat > new_playhead:
                    break
                if note.start_beat >= self._playhead_beat:
                    self._start_note(note)
                self._note_index += 1

            notes_to_stop = []
            for pitch, info in self._active_notes.items():
                end_beat = info["end_beat"]
                if new_playhead >= end_beat and info.get("remaining_samples") is None:
                    release = int(SAMPLE_RATE * 0.05)
                    info["remaining_samples"] = release

            self._playhead_beat = new_playhead

            if self._playhead_beat >= self._total_beats:
                self._song_finished = True

            return consumed

    def _start_note(self, note: MidiNote):
        freq = 440.0 * (2 ** ((note.pitch - 69) / 12))
        if note.pitch in self._active_notes:
            self._active_notes[note.pitch]["remaining_samples"] = int(SAMPLE_RATE * 0.01)

        self._active_notes[note.pitch] = {
            "freq": freq,
            "phase": 0.0,
            "velocity": note.velocity,
            "age_samples": 0,
            "end_beat": note.start_beat + note.duration_beats,
            "remaining_samples": None,
        }

    def is_finished(self) -> bool:
        with self._lock:
            return self._song_finished

    def get_playhead_beats(self) -> float:
        with self._lock:
            return self._playhead_beat

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
            self._active_notes.clear()
