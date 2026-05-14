import os
from pathlib import Path

import yaml


_DEFAULTS = {
    "songsDirectory": "./songs",
    "cacheDirectory": "./.song-cache",
    "soundFontPath": "./soundfonts/default.sf2",
    "keyboard": {
        "countOnly": True,
        "ignoreAutoRepeat": True,
    },
    "playback": {
        "defaultVolume": 0.35,
        "maxCreditBeats": 8,
        "defaultCreditPerKeyBeats": 0.125,
        "fadeMs": 35,
    },
    "import": {
        "createJsonCache": True,
        "runAudioToMidiExtraction": False,
        "preferOriginalAudioForAudioFiles": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    def __init__(self, app_dir: Path | None = None):
        if app_dir is None:
            app_dir = Path(__file__).parent
        self.app_dir = app_dir

        cfg_path = app_dir / "config.yaml"
        user_cfg = {}
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}

        self._data = _deep_merge(_DEFAULTS, user_cfg)

        self.songs_dir = (app_dir / self._data["songsDirectory"]).resolve()
        self.cache_dir = (app_dir / self._data["cacheDirectory"]).resolve()
        self.soundfont_path = (app_dir / self._data["soundFontPath"]).resolve()

        self.songs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def keyboard(self) -> dict:
        return self._data["keyboard"]

    @property
    def playback(self) -> dict:
        return self._data["playback"]

    @property
    def import_settings(self) -> dict:
        return self._data["import"]
