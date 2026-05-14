import logging

from .credit_controller import KeyboardCreditController
from .models import ImportedSong
from .playback_audio import AudioPlaybackEngine
from .playback_midi import MidiPlaybackEngine

logger = logging.getLogger("typetune")


class PlayerRouter:

    def __init__(self, volume: float = 0.35):
        self._audio_engine = AudioPlaybackEngine(volume)
        self._midi_engine = MidiPlaybackEngine(volume)
        self._active_engine: AudioPlaybackEngine | MidiPlaybackEngine | None = None
        self._current_song: ImportedSong | None = None

    def load_song(self, song: ImportedSong):
        if self._active_engine is not None:
            self._active_engine.stop()

        self._current_song = song

        if song.mode == "midi":
            self._midi_engine.load_song(song)
            self._active_engine = self._midi_engine
        else:
            self._audio_engine.load_song(song)
            self._active_engine = self._audio_engine

        logger.info("Routed to %s engine for: %s", song.mode, song.title)

    def tick(self, delta_seconds: float, credit: KeyboardCreditController):
        if self._active_engine is None:
            return

        credit_beats = credit.get_credit()
        consumed = self._active_engine.tick(delta_seconds, credit_beats)
        if consumed > 0:
            credit.consume(consumed)

    def is_current_song_finished(self) -> bool:
        if self._active_engine is None:
            return True
        return self._active_engine.is_finished()

    def stop(self):
        if self._active_engine is not None:
            self._active_engine.stop()
            self._active_engine = None
