import logging
import threading

from .models import ImportedSong
from .song_library import SongLibrary

logger = logging.getLogger("typetune")


class PlaylistController:
    def __init__(self, library: SongLibrary):
        self._library = library
        self._lock = threading.Lock()
        self._index = 0
        self._current: ImportedSong | None = None

    def get_current_song(self) -> ImportedSong | None:
        with self._lock:
            songs = self._library.get_ready_songs()
            if not songs:
                self._current = None
                return None

            self._index = max(0, min(self._index, len(songs) - 1))
            self._current = songs[self._index]
            return self._current

    def next_song(self) -> ImportedSong | None:
        with self._lock:
            songs = self._library.get_ready_songs()
            if not songs:
                self._current = None
                return None

            self._index = (self._index + 1) % len(songs)
            self._current = songs[self._index]
            logger.info("Next song: %s", self._current.title)
            return self._current

    def previous_song(self) -> ImportedSong | None:
        with self._lock:
            songs = self._library.get_ready_songs()
            if not songs:
                self._current = None
                return None

            self._index = (self._index - 1) % len(songs)
            self._current = songs[self._index]
            logger.info("Previous song: %s", self._current.title)
            return self._current

    def restart_current_song(self) -> ImportedSong | None:
        with self._lock:
            return self._current

    def on_library_changed(self):
        with self._lock:
            songs = self._library.get_ready_songs()
            if not songs:
                return

            if self._current is not None:
                for i, s in enumerate(songs):
                    if s.source_hash == self._current.source_hash:
                        self._index = i
                        return

            self._index = min(self._index, len(songs) - 1)
