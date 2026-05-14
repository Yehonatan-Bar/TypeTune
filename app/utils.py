import hashlib
import logging
import time
from pathlib import Path

logger = logging.getLogger("typetune")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
MIDI_EXTENSIONS = {".mid", ".midi"}
ALL_SUPPORTED = AUDIO_EXTENSIONS | MIDI_EXTENSIONS


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in ALL_SUPPORTED


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_midi(path: Path) -> bool:
    return path.suffix.lower() in MIDI_EXTENSIONS


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def wait_until_file_is_stable(
    path: Path, stable_seconds: float = 2.0, timeout_seconds: float = 60.0
) -> bool:
    start = time.time()
    last_size = -1
    stable_since = None

    while time.time() - start < timeout_seconds:
        try:
            size = path.stat().st_size
        except OSError:
            return False

        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= stable_seconds:
                return True
        else:
            stable_since = None
            last_size = size

        time.sleep(0.3)

    return False
