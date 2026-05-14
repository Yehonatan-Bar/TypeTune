from .models import AudioAnalysis, MidiAnalysis, SongBehavior


class BehaviorBuilder:

    def build(self, analysis: AudioAnalysis | MidiAnalysis) -> SongBehavior:
        bpm = analysis.bpm
        confidence = analysis.overall_confidence()

        behavior = SongBehavior()

        if bpm < 80:
            behavior.credit_per_key_beats = 0.18
            behavior.max_credit_beats = 12
            behavior.fade_ms = 60
        elif bpm > 150:
            behavior.credit_per_key_beats = 0.08
            behavior.max_credit_beats = 6
            behavior.fade_ms = 20

        if confidence < 0.6:
            behavior.min_playback_chunk_beats = 2
            behavior.idle_stop_boundary = "soft"
            behavior.allow_tempo_flex = False

        if isinstance(analysis, MidiAnalysis) and confidence > 0.7:
            behavior.min_playback_chunk_beats = 0.5
            behavior.fade_ms = 15

        if isinstance(analysis, AudioAnalysis):
            behavior.fade_ms = max(behavior.fade_ms, 25)

        return behavior
