from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SongBehavior:
    credit_per_key_beats: float = 0.125
    max_credit_beats: float = 8.0
    min_playback_chunk_beats: float = 1.0
    idle_stop_boundary: str = "beat"
    fade_ms: float = 35.0
    allow_tempo_flex: bool = True
    tempo_flex_min: float = 0.92
    tempo_flex_max: float = 1.08

    def to_dict(self) -> dict:
        return {
            "creditPerKeyBeats": self.credit_per_key_beats,
            "maxCreditBeats": self.max_credit_beats,
            "minPlaybackChunkBeats": self.min_playback_chunk_beats,
            "idleStopBoundary": self.idle_stop_boundary,
            "fadeMs": self.fade_ms,
            "allowTempoFlex": self.allow_tempo_flex,
            "tempoFlexMin": self.tempo_flex_min,
            "tempoFlexMax": self.tempo_flex_max,
        }


@dataclass
class MidiNote:
    pitch: int
    start_beat: float
    duration_beats: float
    velocity: int = 80
    channel: int = 0


@dataclass
class AudioAnalysis:
    mode: str = "audio"
    bpm: float = 120.0
    beat_times: list[float] = field(default_factory=list)
    bar_times: list[float] = field(default_factory=list)
    phrase_times: list[float] = field(default_factory=list)
    onset_times: list[float] = field(default_factory=list)
    loudness_curve: list[float] = field(default_factory=list)
    confidence: dict = field(default_factory=lambda: {
        "tempo": 0.5, "beatGrid": 0.5, "phraseBoundaries": 0.3
    })

    def overall_confidence(self) -> float:
        vals = list(self.confidence.values())
        return sum(vals) / len(vals) if vals else 0.5

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "bpm": self.bpm,
            "beatTimesSeconds": self.beat_times,
            "barTimesSeconds": self.bar_times,
            "phraseTimesSeconds": self.phrase_times,
            "onsetTimesSeconds": self.onset_times,
            "loudnessCurve": self.loudness_curve,
            "confidence": self.confidence,
        }


@dataclass
class MidiAnalysis:
    mode: str = "midi"
    bpm: float = 120.0
    ticks_per_beat: int = 480
    notes: list[MidiNote] = field(default_factory=list)
    phrases: list[dict] = field(default_factory=list)
    lead_track_index: int = 0
    confidence: dict = field(default_factory=lambda: {
        "melodyTrack": 0.5, "tempo": 1.0
    })

    def overall_confidence(self) -> float:
        vals = list(self.confidence.values())
        return sum(vals) / len(vals) if vals else 0.5

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "bpm": self.bpm,
            "ticksPerBeat": self.ticks_per_beat,
            "notes": [
                {
                    "pitch": n.pitch,
                    "startBeat": n.start_beat,
                    "durationBeats": n.duration_beats,
                    "velocity": n.velocity,
                    "channel": n.channel,
                }
                for n in self.notes
            ],
            "phrases": self.phrases,
            "confidence": self.confidence,
        }


@dataclass
class ImportedSong:
    source_file: Path
    source_hash: str
    title: str
    mode: str  # "audio" or "midi"
    duration_seconds: float = 0.0
    duration_beats: float = 0.0
    bpm: float = 120.0
    time_signature: tuple[int, int] = (4, 4)
    analysis_confidence: float = 0.5
    behavior: SongBehavior = field(default_factory=SongBehavior)
    analysis: AudioAnalysis | MidiAnalysis | None = None
    cache_dir: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def normalized_audio_path(self) -> Path | None:
        if self.cache_dir:
            p = self.cache_dir / "normalized.wav"
            if p.exists():
                return p
        return None

    @property
    def is_finished_at(self) -> float:
        if self.mode == "audio":
            return self.duration_seconds
        return self.duration_beats
