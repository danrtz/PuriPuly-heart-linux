import os
from pathlib import Path

import pytest

from puripuly_heart.core.vrchat_scene_tailer import (
    VrchatSceneLogTailer,
    VrchatSceneLogTruncated,
    default_vrchat_log_directory,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux filesystem behavior")


def test_append_changes_ctime_but_keeps_tail_position(tmp_path):
    path = tmp_path / "output_log_2026-10-02_10-00-00.txt"
    path.write_text("first\n")
    tailer = VrchatSceneLogTailer(tmp_path)
    assert tailer.begin_replay(path) == ["first"]
    with path.open("a") as output:
        output.write("日本語\n")
    assert tailer.read_new_lines() == ["日本語"]
    assert tailer.read_new_lines() == []
    path.unlink()
    path.write_text("replacement\n")
    with pytest.raises(VrchatSceneLogTruncated):
        tailer.read_new_lines()


def test_steam_external_library_and_environment_override(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("STEAM_COMPAT_DATA_PATH", raising=False)
    monkeypatch.delenv("WINEPREFIX", raising=False)
    monkeypatch.delenv("PURIPULY_VRCHAT_LOG_DIR", raising=False)
    steam = tmp_path / ".local/share/Steam/steamapps"
    steam.mkdir(parents=True)
    library = tmp_path / "VR drive/SteamLibrary"
    logs = (
        library
        / "steamapps/compatdata/438100/pfx/drive_c/users/steamuser/AppData/LocalLow/VRChat/VRChat"
    )
    logs.mkdir(parents=True)
    (steam / "libraryfolders.vdf").write_text(
        '"libraryfolders" { "0" { "path" "' + str(library) + '" } }'
    )
    assert default_vrchat_log_directory() == logs
    custom = tmp_path / "custom"
    monkeypatch.setenv("PURIPULY_VRCHAT_LOG_DIR", str(custom))
    assert default_vrchat_log_directory() == custom
