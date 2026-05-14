import logging
from pathlib import Path

import librosa
import numpy as np
import pretty_midi
import soundfile as sf

from .models import AudioAnalysis, MidiAnalysis, MidiNote

logger = logging.getLogger("typetune")

SAMPLE_RATE = 44100


class SongAnalyzer:

    def normalize_audio(self, source: Path, output: Path) -> float:
        y, sr = librosa.load(str(source), sr=SAMPLE_RATE, mono=False)
        if y.ndim == 1:
            y = np.stack([y, y])
        elif y.shape[0] > 2:
            y = y[:2]

        peak = np.max(np.abs(y))
        if peak > 0:
            y = y / peak * 0.95

        sf.write(str(output), y.T, SAMPLE_RATE, subtype="PCM_16")
        duration = y.shape[1] / SAMPLE_RATE
        logger.info("Normalized audio: %.1fs -> %s", duration, output.name)
        return duration

    def analyze_audio(self, audio_path: Path) -> AudioAnalysis:
        logger.info("Analyzing audio: %s", audio_path.name)
        y, sr = librosa.load(str(audio_path), sr=SAMPLE_RATE, mono=True)
        duration = len(y) / sr

        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        if isinstance(tempo, np.ndarray):
            tempo = float(tempo[0])
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        tempo_confidence = min(1.0, max(0.3, 1.0 - abs(tempo - round(tempo)) / 10.0))

        onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()

        beats_per_bar = 4
        bar_times = beat_times[::beats_per_bar] if beat_times else []

        phrase_length = 4
        phrase_times = bar_times[::phrase_length] if bar_times else []

        beat_confidence = 0.8 if len(beat_times) > 4 else 0.4
        phrase_confidence = 0.5 if len(phrase_times) > 2 else 0.2

        rms = librosa.feature.rms(y=y)[0]
        loudness = (rms / (rms.max() + 1e-8)).tolist() if len(rms) > 0 else []

        analysis = AudioAnalysis(
            bpm=round(tempo, 1),
            beat_times=beat_times,
            bar_times=bar_times,
            phrase_times=phrase_times,
            onset_times=onset_times,
            loudness_curve=loudness,
            confidence={
                "tempo": round(tempo_confidence, 2),
                "beatGrid": round(beat_confidence, 2),
                "phraseBoundaries": round(phrase_confidence, 2),
            },
        )
        logger.info(
            "Audio analysis: BPM=%.1f, %d beats, confidence=%.2f",
            analysis.bpm,
            len(beat_times),
            analysis.overall_confidence(),
        )
        return analysis

    def analyze_midi(self, midi_path: Path) -> MidiAnalysis:
        logger.info("Analyzing MIDI: %s", midi_path.name)
        midi = pretty_midi.PrettyMIDI(str(midi_path))

        bpm = 120.0
        tempos = midi.get_tempo_changes()
        if len(tempos[1]) > 0:
            bpm = float(tempos[1][0])

        tpb = midi.resolution

        ts = (4, 4)
        if midi.time_signature_changes:
            first_ts = midi.time_signature_changes[0]
            ts = (first_ts.numerator, first_ts.denominator)

        lead_idx = self._select_lead_track(midi)
        lead_inst = midi.instruments[lead_idx] if midi.instruments else None

        notes = []
        if lead_inst:
            for n in sorted(lead_inst.notes, key=lambda x: x.start):
                start_beat = midi.time_to_tick(n.start) / tpb
                end_beat = midi.time_to_tick(n.end) / tpb
                dur = end_beat - start_beat

                start_beat = round(start_beat * 16) / 16
                dur = max(1 / 16, round(dur * 16) / 16)

                notes.append(MidiNote(
                    pitch=n.pitch,
                    start_beat=start_beat,
                    duration_beats=dur,
                    velocity=n.velocity,
                    channel=0,
                ))

        notes = self._filter_melody(notes)

        total_beats = 0.0
        if notes:
            total_beats = max(n.start_beat + n.duration_beats for n in notes)

        phrases = []
        phrase_len = ts[0] * 4
        beat = 0.0
        while beat < total_beats:
            phrases.append({"startBeat": beat, "endBeat": min(beat + phrase_len, total_beats)})
            beat += phrase_len

        melody_confidence = 0.9 if lead_inst and not lead_inst.is_drum else 0.5

        analysis = MidiAnalysis(
            bpm=bpm,
            ticks_per_beat=tpb,
            notes=notes,
            phrases=phrases,
            lead_track_index=lead_idx,
            confidence={
                "melodyTrack": round(melody_confidence, 2),
                "tempo": 1.0 if len(tempos[1]) > 0 else 0.7,
            },
        )
        logger.info(
            "MIDI analysis: BPM=%.1f, %d notes, lead track=%d",
            bpm, len(notes), lead_idx,
        )
        return analysis

    def _select_lead_track(self, midi: pretty_midi.PrettyMIDI) -> int:
        instruments = [i for i in midi.instruments if not i.is_drum]
        if not instruments:
            instruments = midi.instruments
        if not instruments:
            return 0

        lead_keywords = ["melody", "lead", "vocal", "right", "treble"]
        for i, inst in enumerate(instruments):
            name = (inst.name or "").lower()
            if any(kw in name for kw in lead_keywords):
                return midi.instruments.index(inst)

        def score_track(inst):
            if not inst.notes:
                return -1
            pitches_at_time = {}
            for n in inst.notes:
                t = round(n.start, 2)
                pitches_at_time.setdefault(t, []).append(n.pitch)
            avg_polyphony = np.mean([len(v) for v in pitches_at_time.values()])
            avg_pitch = np.mean([n.pitch for n in inst.notes])
            note_count = len(inst.notes)
            mono_score = 1.0 / (avg_polyphony + 0.1)
            return mono_score * 3 + avg_pitch / 127 * 2 + min(note_count / 100, 1.0)

        best = max(instruments, key=score_track)
        return midi.instruments.index(best)

    def _filter_melody(self, notes: list[MidiNote]) -> list[MidiNote]:
        if not notes:
            return notes

        min_duration = 1 / 16
        notes = [n for n in notes if n.duration_beats >= min_duration]

        windows: dict[float, list[MidiNote]] = {}
        for n in notes:
            key = round(n.start_beat * 8) / 8
            windows.setdefault(key, []).append(n)

        melody = []
        last_pitch = None
        for key in sorted(windows.keys()):
            group = windows[key]
            if len(group) == 1:
                chosen = group[0]
            else:
                def note_score(n):
                    pitch_score = n.pitch / 127
                    vel_score = n.velocity / 127
                    proximity = 0
                    if last_pitch is not None:
                        proximity = 1.0 / (1 + abs(n.pitch - last_pitch))
                    return pitch_score * 2 + vel_score + proximity * 3

                chosen = max(group, key=note_score)
            melody.append(chosen)
            last_pitch = chosen.pitch

        return melody
