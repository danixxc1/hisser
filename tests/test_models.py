from __future__ import annotations

import json
from pathlib import Path

import pytest

from hisser.models import LARGE_V3_Q5, TURBO_Q5, load_profile, model_for_filename


def test_missing_profile_preserves_current_model_and_safe_threads(tmp_path):
    profile = load_profile(tmp_path)
    assert profile.model is LARGE_V3_Q5
    assert profile.cpu_threads == 6
    assert not list(tmp_path.iterdir())


def test_profile_selects_only_pinned_catalog_model(tmp_path):
    (tmp_path / "transcription-profile.json").write_text(json.dumps({"model_id": TURBO_Q5.id, "cpu_threads": 4}), encoding="utf-8")
    profile = load_profile(tmp_path)
    assert profile.model is TURBO_Q5
    assert profile.model.filename == "ggml-large-v3-turbo-q5_0.bin"
    assert profile.model.size == 574_041_195
    assert len(profile.model.sha256) == 64
    assert profile.cpu_threads == 4
    assert model_for_filename(TURBO_Q5.filename) is TURBO_Q5
    assert model_for_filename("unknown.bin") is None


@pytest.mark.parametrize("payload", [
    None, [], {"model_id": "../other.bin"}, {"model_id": "C:/other.bin"},
    {"model_id": "tiny"}, {"model_id": None}, {"cpu_threads": True},
    {"cpu_threads": 0}, {"cpu_threads": 33}, {"cpu_threads": "6"},
])
def test_invalid_profile_cannot_select_unverified_model_or_resource_count(tmp_path, payload):
    (tmp_path / "transcription-profile.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="profile is damaged"):
        load_profile(tmp_path)


def test_corrupt_json_is_actionable(tmp_path):
    (tmp_path / "transcription-profile.json").write_text("{unfinished", encoding="utf-8")
    with pytest.raises(ValueError, match="profile is damaged"):
        load_profile(tmp_path)
