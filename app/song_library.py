import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileDeletedEvent, FileModifiedEvent
from watchdog.observers import Observer

from .config import Config
from .models import ImportedSong
from .song_importer import SongImporter
from .utils import is_supported

logger = logging.getLogger("typetune")


class SongLibrary:
    def __init__(self, config: Config):
        self._config = config
        self._importer = SongImporter(config)
        self._songs: dict[str, ImportedSong] = {}
        self._lock = threading.Lock()
        self._observer: Observer | None = None
        self._on_change_callback = None

    def set_on_change(self, callback):
        self._on_change_callback = callback

    def scan(self):
        logger.info("Scanning songs directory: %s", self._config.songs_dir)
        for path in sorted(self._config.songs_dir.iterdir()):
            if path.is_file() and is_supported(path):
                self._try_import(path)

        logger.info("Scan complete: %d songs ready", len(self._songs))

    def start_watcher(self):
        handler = _SongFolderHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._config.songs_dir), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("File watcher started on: %s", self._config.songs_dir)

    def stop_watcher(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

    def on_file_added(self, path: Path):
        if not is_supported(path):
            return
        logger.info("File added: %s", path.name)
        self._try_import(path)

    def on_file_removed(self, path: Path):
        key = str(path)
        with self._lock:
            if key in self._songs:
                title = self._songs[key].title
                del self._songs[key]
                logger.info("Removed from playlist: %s", title)
                if self._on_change_callback:
                    self._on_change_callback()

    def on_file_modified(self, path: Path):
        if not is_supported(path):
            return
        key = str(path)
        with self._lock:
            if key in self._songs:
                del self._songs[key]
        self._try_import(path)

    def get_ready_songs(self) -> list[ImportedSong]:
        with self._lock:
            return list(self._songs.values())

    def _try_import(self, path: Path):
        try:
            song = self._importer.import_file(path)
            if song:
                with self._lock:
                    self._songs[str(path)] = song
                logger.info("Added to playlist: %s (%s mode)", song.title, song.mode)
                if self._on_change_callback:
                    self._on_change_callback()
        except Exception:
            logger.exception("Failed to import: %s", path.name)


class _SongFolderHandler(FileSystemEventHandler):
    def __init__(self, library: SongLibrary):
        self._library = library

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            self._library.on_file_added(Path(event.src_path))

    def on_deleted(self, event):
        if isinstance(event, FileDeletedEvent) and not event.is_directory:
            self._library.on_file_removed(Path(event.src_path))

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            self._library.on_file_modified(Path(event.src_path))
