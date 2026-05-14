import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .behavior_builder import BehaviorBuilder
from .config import Config
from .models import AudioAnalysis, ImportedSong, MidiAnalysis, SongBehavior
from .song_analyzer import SongAnalyzer
from .utils import compute_file_hash, is_audio, is_midi, is_supported, wait_until_file_is_stable

logger = logging.getLogger("typetune")


class SongImporter:
    def __init__(self, config: Config):
        self._config = config
        self._analyzer = SongAnalyzer()
        self._behavior_builder = BehaviorBuilder()

    def import_file(self, path: Path) -> ImportedSong | None:
        if not path.exists():
            logger.warning("File does not exist: %s", path)
            return None

        if not is_supported(path):
            logger.info("Unsupported file type: %s", path.suffix)
            return None

        logger.info("Importing: %s", path.name)

        if not wait_until_file_is_stable(path):
            logger.warning("File not stable (still copying?): %s", path.name)
            return None

        file_hash = compute_file_hash(path)
        cache_dir = self._config.cache_dir / file_hash
        manifest_path = cache_dir / "manifest.json"

        if manifest_path.exists():
            logger.info("Using cached import for: %s", path.name)
            return self._load_from_cache(path, cache_dir, manifest_path)

        cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            if is_midi(path):
                return self._import_midi(path, file_hash, cache_dir)
            elif is_audio(path):
                return self._import_audio(path, file_hash, cache_dir)
        except Exception:
            logger.exception("Import failed for: %s", path.name)
            return None

        return None

    def _import_midi(self, path: Path, file_hash: str, cache_dir: Path) -> ImportedSong:
        analysis = self._analyzer.analyze_midi(path)
        behavior = self._behavior_builder.build(analysis)

        total_beats = 0.0
        if analysis.notes:
            total_beats = max(n.start_beat + n.duration_beats for n in analysis.notes)

        duration_seconds = total_beats / analysis.bpm * 60 if analysis.bpm > 0 else 0

        song = ImportedSong(
            source_file=path,
            source_hash=file_hash,
            title=path.stem,
            mode="midi",
            duration_seconds=duration_seconds,
            duration_beats=total_beats,
            bpm=analysis.bpm,
            time_signature=(4, 4),
            analysis_confidence=analysis.overall_confidence(),
            behavior=behavior,
            analysis=analysis,
            cache_dir=cache_dir,
        )

        self._save_analysis(cache_dir, analysis)
        self._save_manifest(song)

        logger.info("Imported MIDI: %s (%.0f BPM, %d notes)", path.name, analysis.bpm, len(analysis.notes))
        return song

    def _import_audio(self, path: Path, file_hash: str, cache_dir: Path) -> ImportedSong:
        normalized_path = cache_dir / "normalized.wav"
        duration = self._analyzer.normalize_audio(path, normalized_path)

        analysis = self._analyzer.analyze_audio(normalized_path)
        behavior = self._behavior_builder.build(analysis)

        song = ImportedSong(
            source_file=path,
            source_hash=file_hash,
            title=path.stem,
            mode="audio",
            duration_seconds=duration,
            duration_beats=duration * analysis.bpm / 60,
            bpm=analysis.bpm,
            time_signature=(4, 4),
            analysis_confidence=analysis.overall_confidence(),
            behavior=behavior,
            analysis=analysis,
            cache_dir=cache_dir,
        )

        self._save_analysis(cache_dir, analysis)
        self._save_manifest(song)

        logger.info("Imported audio: %s (%.0f BPM, %.1fs)", path.name, analysis.bpm, duration)
        return song

    def _save_analysis(self, cache_dir: Path, analysis):
        path = cache_dir / "analysis.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(analysis.to_dict(), f, indent=2)

    def _save_manifest(self, song: ImportedSong):
        manifest = {
            "schemaVersion": 1,
            "sourceFile": str(song.source_file),
            "sourceHash": song.source_hash,
            "title": song.title,
            "artist": None,
            "importedAt": datetime.now(timezone.utc).isoformat(),
            "mode": song.mode,
            "durationSeconds": round(song.duration_seconds, 2),
            "estimatedBpm": song.bpm,
            "timeSignature": {
                "numerator": song.time_signature[0],
                "denominator": song.time_signature[1],
            },
            "analysisConfidence": round(song.analysis_confidence, 2),
            "paths": {
                "analysis": str(song.cache_dir / "analysis.json"),
            },
            "behavior": song.behavior.to_dict(),
        }

        if song.mode == "audio":
            manifest["paths"]["normalizedAudio"] = str(song.cache_dir / "normalized.wav")
            manifest["durationBeats"] = round(song.duration_beats, 2)
        else:
            manifest["durationBeats"] = round(song.duration_beats, 2)
            manifest["leadTrackIndex"] = (
                song.analysis.lead_track_index if isinstance(song.analysis, MidiAnalysis) else 0
            )

        path = song.cache_dir / "manifest.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _load_from_cache(
        self, source_path: Path, cache_dir: Path, manifest_path: Path
    ) -> ImportedSong | None:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            analysis_path = cache_dir / "analysis.json"
            analysis = None
            if analysis_path.exists():
                with open(analysis_path, "r", encoding="utf-8") as f:
                    analysis_data = json.load(f)
                analysis = self._rebuild_analysis(analysis_data)

            behavior_data = manifest.get("behavior", {})
            behavior = SongBehavior(
                credit_per_key_beats=behavior_data.get("creditPerKeyBeats", 0.125),
                max_credit_beats=behavior_data.get("maxCreditBeats", 8),
                min_playback_chunk_beats=behavior_data.get("minPlaybackChunkBeats", 1),
                idle_stop_boundary=behavior_data.get("idleStopBoundary", "beat"),
                fade_ms=behavior_data.get("fadeMs", 35),
                allow_tempo_flex=behavior_data.get("allowTempoFlex", True),
                tempo_flex_min=behavior_data.get("tempoFlexMin", 0.92),
                tempo_flex_max=behavior_data.get("tempoFlexMax", 1.08),
            )

            ts = manifest.get("timeSignature", {})

            return ImportedSong(
                source_file=source_path,
                source_hash=manifest["sourceHash"],
                title=manifest.get("title", source_path.stem),
                mode=manifest["mode"],
                duration_seconds=manifest.get("durationSeconds", 0),
                duration_beats=manifest.get("durationBeats", 0),
                bpm=manifest.get("estimatedBpm", 120),
                time_signature=(ts.get("numerator", 4), ts.get("denominator", 4)),
                analysis_confidence=manifest.get("analysisConfidence", 0.5),
                behavior=behavior,
                analysis=analysis,
                cache_dir=cache_dir,
            )
        except Exception:
            logger.exception("Failed to load cache for %s", source_path.name)
            return None

    def _rebuild_analysis(self, data: dict):
        mode = data.get("mode", "audio")
        if mode == "midi":
            from .models import MidiNote

            notes = [
                MidiNote(
                    pitch=n["pitch"],
                    start_beat=n["startBeat"],
                    duration_beats=n["durationBeats"],
                    velocity=n.get("velocity", 80),
                    channel=n.get("channel", 0),
                )
                for n in data.get("notes", [])
            ]
            return MidiAnalysis(
                bpm=data.get("bpm", 120),
                ticks_per_beat=data.get("ticksPerBeat", 480),
                notes=notes,
                phrases=data.get("phrases", []),
                confidence=data.get("confidence", {}),
            )
        else:
            return AudioAnalysis(
                bpm=data.get("bpm", 120),
                beat_times=data.get("beatTimesSeconds", []),
                bar_times=data.get("barTimesSeconds", []),
                phrase_times=data.get("phraseTimesSeconds", []),
                onset_times=data.get("onsetTimesSeconds", []),
                loudness_curve=data.get("loudnessCurve", []),
                confidence=data.get("confidence", {}),
            )
