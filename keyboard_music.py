import json
import math
import os
import sys
import numpy as np
import pygame
from pynput import keyboard

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_LIB = os.path.join(SCRIPT_DIR, "music_lib")
CACHE_DIR = os.path.join(MUSIC_LIB, ".cache")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac"}
MIDI_EXTENSIONS = {".mid", ".midi"}


def note_name_to_hz(name):
    if name == "REST":
        return 0
    notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    if len(name) >= 3 and name[1] == "#":
        note, octave = name[:2], int(name[2:])
    elif len(name) >= 3 and name[1] == "b":
        flat_map = {"Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B"}
        note, octave = flat_map.get(name[:2], name[:2]), int(name[2:])
    else:
        note, octave = name[0], int(name[1:])
    midi_num = notes.index(note) + (octave + 1) * 12
    return 440.0 * (2 ** ((midi_num - 69) / 12))


def hz_to_note_name(freq):
    if freq <= 0:
        return "REST"
    notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    midi_num = round(12 * math.log2(freq / 440.0) + 69)
    return f"{notes[midi_num % 12]}{(midi_num // 12) - 1}"


def extract_from_midi(path):
    import pretty_midi
    midi = pretty_midi.PrettyMIDI(path)
    all_notes = []
    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            name = pretty_midi.note_number_to_name(note.pitch)
            all_notes.append((note.start, name))
    all_notes.sort(key=lambda x: x[0])
    return [n[1] for n in all_notes] if all_notes else ["REST"]


def extract_from_audio(path):
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    f0, voiced_flag, _ = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
    )

    hop_length = 512
    frame_duration = hop_length / sr
    min_frames = max(1, int(0.06 / frame_duration))

    raw = []
    for freq, voiced in zip(f0, voiced_flag):
        if voiced and not np.isnan(freq):
            raw.append(hz_to_note_name(freq))
        else:
            raw.append("REST")

    if not raw:
        return ["REST"]

    consolidated = []
    current = raw[0]
    count = 1
    for n in raw[1:]:
        if n == current:
            count += 1
        else:
            if count >= min_frames and current != "REST":
                consolidated.append(current)
            elif count >= min_frames * 4 and current == "REST":
                consolidated.append("REST")
            current = n
            count = 1
    if count >= min_frames and current != "REST":
        consolidated.append(current)

    return consolidated if consolidated else ["REST"]


def load_or_extract(filepath, filename):
    ext = os.path.splitext(filename)[1].lower()
    name = os.path.splitext(filename)[0]

    if ext == ".json":
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    cache_path = os.path.join(CACHE_DIR, f"{name}.json")
    if os.path.isfile(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(filepath):
        with open(cache_path, "r", encoding="utf-8") as f:
            print(f"  {filename} (cached)")
            return json.load(f)

    if ext in MIDI_EXTENSIONS:
        print(f"  {filename} — extracting notes from MIDI...")
        notes = extract_from_midi(filepath)
    elif ext in AUDIO_EXTENSIONS:
        print(f"  {filename} — analyzing audio (this may take a moment)...")
        notes = extract_from_audio(filepath)
    else:
        return None

    song = {"name": name, "notes": notes}
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(song, f, indent=2)
    print(f"    Found {len(notes)} notes, cached for next time.")
    return song


def load_songs():
    if not os.path.isdir(MUSIC_LIB):
        os.makedirs(MUSIC_LIB)
        print(f"Created: {MUSIC_LIB}")
        print("Drop your music files there (.mp3, .wav, .mid, .ogg, .flac) and restart.")
        sys.exit(0)

    songs = []
    for filename in sorted(os.listdir(MUSIC_LIB)):
        if filename.startswith("."):
            continue
        filepath = os.path.join(MUSIC_LIB, filename)
        if not os.path.isfile(filepath):
            continue
        song = load_or_extract(filepath, filename)
        if song:
            songs.append(song)

    if not songs:
        print(f"No songs found in {MUSIC_LIB}")
        print("Drop your music files there (.mp3, .wav, .mid, .ogg, .flac) and restart.")
        sys.exit(0)

    return songs


def make_tone(freq, duration_ms=180, volume=0.35):
    sample_rate = 44100
    sample_count = int(sample_rate * duration_ms / 1000)

    if freq == 0:
        samples = np.zeros(sample_count)
    else:
        t = np.linspace(0, duration_ms / 1000, sample_count, False)
        samples = np.sin(freq * t * 2 * math.pi)
        fade_len = min(300, len(samples) // 8)
        samples[:fade_len] *= np.linspace(0, 1, fade_len)
        samples[-fade_len:] *= np.linspace(1, 0, fade_len)

    mono = (samples * volume * 32767).astype(np.int16)
    audio = np.column_stack((mono, mono))
    return pygame.sndarray.make_sound(audio)


sound_cache = {}


def get_sound(note_name):
    if note_name not in sound_cache:
        sound_cache[note_name] = make_tone(note_name_to_hz(note_name))
    return sound_cache[note_name]


pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

print("=== TypeTune ===")
print("Loading songs...")
songs = load_songs()

all_notes = {n for song in songs for n in song["notes"]}
for note in all_notes:
    get_sound(note)

song_index = 0
note_index = 0
pressed_keys = set()
active = True


def play_next_note():
    global song_index, note_index

    note = songs[song_index]["notes"][note_index]
    get_sound(note).play()
    note_index += 1

    if note_index >= len(songs[song_index]["notes"]):
        note_index = 0
        song_index = (song_index + 1) % len(songs)
        print(f"Now playing: {songs[song_index]['name']}")


def on_press(key):
    global active

    if key == keyboard.Key.f12:
        active = not active
        print("Active:", active)
        return

    if key in pressed_keys:
        return
    pressed_keys.add(key)

    if active:
        play_next_note()


def on_release(key):
    pressed_keys.discard(key)


print(f"Loaded {len(songs)} songs:")
for i, s in enumerate(songs):
    print(f"  {i + 1}. {s['name']} ({len(s['notes'])} notes)")
print(f"\nNow playing: {songs[0]['name']}")
print("Press any key to advance | F12 = pause/resume | Ctrl+C = stop\n")

with keyboard.Listener(on_press=on_press, on_release=on_release, suppress=False) as listener:
    listener.join()
