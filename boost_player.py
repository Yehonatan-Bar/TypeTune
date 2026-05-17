"""
TypeTune Boost Player
---------------------
Plays all songs from the songs folder continuously.
Keyboard input temporarily boosts volume by 3x, then decays back.
Runs independently of the main TypeTune app.
"""

import math
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from pynput import keyboard

SONGS_DIR = Path(__file__).parent / "app" / "songs"
SAMPLE_RATE = 44100
BASE_VOLUME = 0.12
BOOST_MULTIPLIER = 5.0
DECAY_RATE = 8.0
SUPPORTED = (".mp3", ".wav", ".flac", ".m4a", ".ogg")
BLOCK_SIZE = 1024

_DECAY_FACTOR = math.exp(-DECAY_RATE / SAMPLE_RATE)


def load_audio(path: Path) -> np.ndarray:
    import librosa
    y, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y], axis=1)
    elif y.shape[0] == 2:
        y = y.T
    return y.astype(np.float32)


def find_songs() -> list[Path]:
    songs = []
    for ext in SUPPORTED:
        songs.extend(SONGS_DIR.glob(f"*{ext}"))
    return sorted(songs)


class BoostPlayer:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: np.ndarray | None = None
        self._pos = 0
        self._len = 0
        self._finished = True
        self._stream: sd.OutputStream | None = None
        self._boost = 1.0
        self._paused = False

    def boost(self):
        self._boost = BOOST_MULTIPLIER

    def toggle_pause(self):
        self._paused = not self._paused
        state = "PAUSED" if self._paused else "PLAYING"
        print(f"  [{state}]")

    def load(self, path: Path) -> bool:
        self.stop()
        print(f"  Loading: {path.name}...", end=" ", flush=True)
        try:
            data = load_audio(path)
        except Exception as e:
            print(f"error: {e}")
            return False

        with self._lock:
            self._data = data
            self._pos = 0
            self._len = len(data)
            self._finished = False

        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=2,
            dtype="float32",
            callback=self._callback,
            blocksize=BLOCK_SIZE,
        )
        self._stream.start()
        print("ok")
        return True

    def _callback(self, out, frames, time_info, status):
        with self._lock:
            if self._data is None or self._finished or self._paused:
                out[:] = 0
                return

            end = min(self._pos + frames, self._len)
            n = end - self._pos
            if n <= 0:
                out[:] = 0
                self._finished = True
                return

            chunk = self._data[self._pos:end].copy()

            b = self._boost
            if b > 1.001:
                excess = b - 1.0
                decay_curve = _DECAY_FACTOR ** np.arange(n, dtype=np.float32)
                envelope = (1.0 + excess * decay_curve) * BASE_VOLUME
                self._boost = 1.0 + excess * (_DECAY_FACTOR ** n)
                chunk *= envelope[:, np.newaxis]
            else:
                self._boost = 1.0
                chunk *= BASE_VOLUME

            out[:n] = chunk
            if n < frames:
                out[n:] = 0
            self._pos = end
            if end >= self._len:
                self._finished = True

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            self._data = None


def main():
    SONGS_DIR.mkdir(parents=True, exist_ok=True)

    print("=== TypeTune Boost Player ===")
    print(f"Songs folder: {SONGS_DIR}")
    print("Music plays continuously. Typing boosts volume 5x.")
    print("F12 = pause/resume | Ctrl+C = quit\n")

    songs = find_songs()
    if not songs:
        print(f"No songs found in: {SONGS_DIR}")
        print("Drop audio files there (.mp3, .wav, .flac, .m4a, .ogg)")
        print("Waiting for songs...")
        while not songs:
            time.sleep(2)
            songs = find_songs()

    print(f"Found {len(songs)} song(s):")
    for i, s in enumerate(songs):
        print(f"  {i + 1}. {s.name}")
    print()

    player = BoostPlayer()
    pressed = set()

    def on_press(key):
        if key == keyboard.Key.f12:
            player.toggle_pause()
            return

        kid = id(key)
        if kid in pressed:
            return
        pressed.add(kid)
        player.boost()

    def on_release(key):
        pressed.discard(id(key))

    listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
        suppress=False,
    )
    listener.daemon = True
    listener.start()

    idx = 0
    try:
        while True:
            song = songs[idx % len(songs)]
            if player.load(song):
                print(f"  Now playing: {song.stem}")

            while not player.finished:
                time.sleep(0.05)

            idx += 1
            if idx >= len(songs):
                idx = 0
                songs = find_songs()
                if not songs:
                    print("\nNo songs left. Waiting...")
                    while not songs:
                        time.sleep(2)
                        songs = find_songs()

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        player.stop()
        listener.stop()


if __name__ == "__main__":
    main()
