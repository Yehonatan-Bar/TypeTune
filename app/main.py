import logging
import sys
import time
from pathlib import Path

from pynput import keyboard

from .config import Config
from .credit_controller import KeyboardCreditController
from .playback_router import PlayerRouter
from .playlist_controller import PlaylistController
from .song_library import SongLibrary

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(app_dir: Path):
    log_dir = app_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    app_dir = Path(__file__).parent
    setup_logging(app_dir)
    logger = logging.getLogger("typetune")

    logger.info("=== TypeTune ===")
    logger.info("Starting up...")

    config = Config(app_dir)

    library = SongLibrary(config)
    playlist = PlaylistController(library)
    library.set_on_change(playlist.on_library_changed)

    credit = KeyboardCreditController(
        default_credit_per_key=config.playback["defaultCreditPerKeyBeats"],
        max_credit=config.playback["maxCreditBeats"],
    )

    player = PlayerRouter(volume=config.playback["defaultVolume"])

    print("=== TypeTune ===")
    print(f"Songs folder: {config.songs_dir}")
    print("Scanning for songs...")

    library.scan()
    library.start_watcher()

    songs = library.get_ready_songs()
    if not songs:
        print(f"\nNo songs found in: {config.songs_dir}")
        print("Drop music files there (.mp3, .wav, .mid, .flac, .m4a, .ogg)")
        print("Waiting for songs...")

        while not library.get_ready_songs():
            time.sleep(1)

        songs = library.get_ready_songs()

    print(f"\nLoaded {len(songs)} song(s):")
    for i, s in enumerate(songs):
        print(f"  {i + 1}. {s.title} ({s.mode}, {s.bpm:.0f} BPM)")

    current_song = playlist.get_current_song()
    if current_song:
        player.load_song(current_song)
        credit.configure(current_song.behavior)
        print(f"\nNow playing: {current_song.title}")

    print("\nType anywhere to advance the music")
    print("F12 = pause/resume | Ctrl+C = quit\n")

    paused = False
    pressed_keys = set()

    def on_press(key):
        nonlocal paused

        if key == keyboard.Key.f12:
            paused = not paused
            state = "PAUSED" if paused else "ACTIVE"
            print(f"[{state}]")
            return

        key_id = id(key)
        if key_id in pressed_keys:
            return
        pressed_keys.add(key_id)

        if not paused:
            credit.on_key_press()

    def on_release(key):
        pressed_keys.discard(id(key))

    listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
        suppress=False,
    )
    listener.daemon = True
    listener.start()

    try:
        last_time = time.perf_counter()

        while True:
            now = time.perf_counter()
            delta = now - last_time
            last_time = now

            if not paused and current_song:
                player.tick(delta, credit)

                if player.is_current_song_finished():
                    current_song = playlist.next_song()
                    if current_song:
                        player.load_song(current_song)
                        credit.configure(current_song.behavior)
                        print(f"Now playing: {current_song.title}")
                    else:
                        print("No more songs in playlist.")

            time.sleep(0.005)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        player.stop()
        library.stop_watcher()
        listener.stop()
        logger.info("TypeTune stopped.")


if __name__ == "__main__":
    main()
