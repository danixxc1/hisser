"""Release privacy and integrity boundaries, using tiny fake program inputs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from hisser.models import ModelSpec


SPEC = importlib.util.spec_from_file_location(
    "package_release", Path(__file__).resolve().parents[1] / "scripts" / "package-release.py")
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)


def put(root, relative, value=b"program"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(value, bytes):
        value = json.dumps(value).encode("utf-8")
    path.write_bytes(value)
    return path


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    app = tmp_path / "installed"
    project = tmp_path / "source"
    legal = project / "licenses"
    model_bytes = b"verified model bytes"
    model = ModelSpec("large-v3-q5_0", "ggml-large-v3-q5_0.bin", "Large-v3",
                      len(model_bytes), hashlib.sha256(model_bytes).hexdigest())
    monkeypatch.setattr(release, "MODELS", {model.id: model})
    exe = put(app, "Hisser.exe")
    put(app, "build-manifest.json", {"name": "Hisser", "version": "1.1.0", "backend": "cpu",
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "private": "C:\\Users\\Someone"})
    for name in release.CPU_NAMES:
        put(app, "_internal/runtime/" + name)
    for name in ("base_library.zip", "python314.dll", "_tkinter.pyd", "assets/hisser.ico"):
        put(app, "_internal/" + name)
    put(app, "_internal/runtime/provenance.json", {"model": "obsolete Turbo", "path": "C:\\Users\\Someone"})
    put(app, "_internal/runtime/licenses/old-notice.txt", b"old local notice")
    put(app, "_internal/assets/hisser-source.png", b"unneeded source image")
    put(app, "data/transcription-profile.json", {"model_id": model.id, "cpu_threads": 2,
                                                "input_dir": "C:\\Users\\Someone"})
    put(app, "data/models/" + model.filename, model_bytes)
    put(app, "data/models/" + model.filename + ".metadata.json", {
        "name": model.filename, "size": model.size, "sha256": model.sha256,
        "path": "C:\\Users\\Someone\\private-model", "secret": "never share"})
    put(app, "data/settings.json", {"input_dir": "C:\\Users\\Someone\\Private"})
    put(app, "data/temp/private-audio.wav", b"private audio")
    put(app, "data/transcript.json", b"private dialogue")
    put(app, ".portable-self-test.json", {"data_root": str(app)})
    put(app, "portable.json", {"created_by": "Someone"})
    put(app, "USER_GUIDE.md", b"stale private local guide")
    put(project, "USER_GUIDE.md", b"Public user guide")
    put(project, "THIRD_PARTY_NOTICES.md", b"Public component notices")
    put(project, "LICENSE", b"MIT License")
    put(legal, "component-license.txt", b"Public component license")
    return app, project, legal, model


def collect(inputs, **kwargs):
    app, project, legal, _ = inputs
    return release.collect_entries(app, "1.1.0", legal, project, **kwargs)


def test_archive_contains_only_clean_portable_data_and_verified_bytes(inputs, tmp_path):
    entries, identity = collect(inputs)
    before = (inputs[0] / "data/settings.json").read_bytes()
    result = release.write_release(entries, identity, tmp_path / "release")
    archive = Path(result["archive"])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == result["sha256"]
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert all(name.startswith("Hisser/") for name in names)
        assert "Hisser/Hisser.exe" in names
        assert "Hisser/data/models/ggml-large-v3-q5_0.bin" in names
        assert not any("settings" in name or "private-audio" in name or ".portable-self-test" in name
                       or "hisser-source" in name or "old-notice" in name for name in names)
        profile = json.loads(bundle.read("Hisser/data/transcription-profile.json"))
        assert profile == {"model_id": "large-v3-q5_0", "cpu_threads": 6}
        assert bundle.read("Hisser/USER_GUIDE.md") == b"Public user guide"
        for name in names:
            if name.endswith((".json", ".txt", ".md")):
                assert b"Someone" not in bundle.read(name)
                assert b"C:\\" not in bundle.read(name)
        manifest = json.loads(bundle.read("Hisser/release-manifest.json"))
        for record in manifest["files"]:
            content = bundle.read("Hisser/" + record["path"])
            assert len(content) == record["size"]
            assert hashlib.sha256(content).hexdigest() == record["sha256"]
        assert len(manifest["files"]) == len(names) - 1
    assert (inputs[0] / "data/settings.json").read_bytes() == before
    assert (archive.parent / (archive.name + ".sha256")).read_text().split()[0] == result["sha256"]


def test_wrong_model_hash_discards_partial_archive(inputs, tmp_path):
    entries, identity = collect(inputs)
    model_path = inputs[0] / "data/models" / inputs[3].filename
    model_path.write_bytes(b"x" * inputs[3].size)
    output = tmp_path / "release"
    with pytest.raises(release.ReleaseError, match="SHA-256"):
        release.write_release(entries, identity, output)
    assert not list(output.iterdir())


def test_unknown_program_file_requires_explicit_review(inputs):
    put(inputs[0], "_internal/private-notes.txt", b"private")
    with pytest.raises(release.ReleaseError, match="Unrecognized program file"):
        collect(inputs)


def test_cannot_disguise_an_unknown_model_with_metadata(inputs):
    put(inputs[0], "data/transcription-profile.json", {"model_id": "untrusted"})
    with pytest.raises(release.ReleaseError, match="verified catalog"):
        collect(inputs)


@pytest.mark.parametrize("relative", ["../secret.txt", "/absolute", "C:/private", "a\\b", "a/../b", "./file",
                                      "CON.txt", "a/trailing.", "a/file:name", "a/line\nbreak"])
def test_unsafe_archive_paths_are_rejected(relative, tmp_path):
    with pytest.raises(release.ReleaseError, match="Unsafe archive entry"):
        release.write_release([release.Entry(relative, content=b"unsafe")],
                              {"version": "1.1.0"}, tmp_path / "release")


def test_linked_program_input_is_rejected(inputs, tmp_path):
    link = inputs[0] / "_internal" / "extra.dll"
    destination = put(tmp_path, "private.dll")
    try:
        link.symlink_to(destination)
    except OSError:
        pytest.skip("Creating symlinks is unavailable for this Windows user")
    with pytest.raises(release.ReleaseError, match="Linked"):
        collect(inputs)


def test_linked_source_ancestor_is_rejected(inputs, tmp_path):
    linked = tmp_path / "linked-app"
    try:
        linked.symlink_to(inputs[0], target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable for this Windows user")
    with pytest.raises(release.ReleaseError, match="Linked"):
        release.collect_entries(linked, "1.1.0", inputs[2], inputs[1])


@pytest.mark.skipif(os.name != "nt", reason="Windows junction-specific boundary")
def test_windows_junction_input_is_rejected_without_following_it(inputs, tmp_path):
    linked = tmp_path / "junction-app"
    command = ("New-Item -ItemType Junction -Path '" + str(linked).replace("'", "''")
               + "' -Target '" + str(inputs[0]).replace("'", "''") + "' | Out-Null")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True)
    if result.returncode:
        pytest.skip("Creating Windows junctions is unavailable for this user")
    try:
        with pytest.raises(release.ReleaseError, match="Linked|Reparse"):
            release.collect_entries(linked, "1.1.0", inputs[2], inputs[1])
    finally:
        linked.rmdir()  # Removes the junction itself; never traverses its target.
    assert (inputs[0] / "Hisser.exe").is_file()


def test_public_notices_cannot_copy_personal_paths(inputs):
    put(inputs[2], "oops.txt", b"Copied from C:\\Users\\Someone\\secret.txt")
    with pytest.raises(release.ReleaseError, match="local path"):
        collect(inputs)


def test_public_notices_allow_upstream_https_license_links(inputs):
    notice = b"License: https://www.python.org/psf/license/\nSource: https://github.com/FFmpeg/FFmpeg\n"
    put(inputs[2], "linked-license.txt", notice)
    entries, _ = collect(inputs)
    assert next(entry.content for entry in entries if entry.relative == "licenses/linked-license.txt") == notice


@pytest.mark.parametrize("path", ["C:/Users/Someone/private.txt", "C:\\Users\\Someone\\private.txt"])
def test_public_notices_reject_both_windows_profile_path_styles(inputs, path):
    put(inputs[2], "local-source.txt", ("Local source: " + path).encode("utf-8"))
    with pytest.raises(release.ReleaseError, match="local path"):
        collect(inputs)


def test_archive_limits_and_existing_release_are_enforced(inputs, tmp_path, monkeypatch):
    entries, identity = collect(inputs)
    monkeypatch.setattr(release, "MAX_FOLDER_BYTES", 1)
    with pytest.raises(release.ReleaseError, match="4 GB"):
        release.write_release(entries, identity, tmp_path / "too-large-extracted")
    assert not list((tmp_path / "too-large-extracted").iterdir())
    monkeypatch.setattr(release, "MAX_FOLDER_BYTES", 4_000_000_000)
    monkeypatch.setattr(release, "MAX_ASSET_BYTES", 1)
    output = tmp_path / "oversized"
    with pytest.raises(release.ReleaseError, match="2 GiB"):
        release.write_release(entries, identity, output)
    assert not list(output.iterdir())
    monkeypatch.setattr(release, "MAX_ASSET_BYTES", 2 * 1024**3)
    output = tmp_path / "existing"
    release.write_release(entries, identity, output)
    with pytest.raises(release.ReleaseError, match="already exists"):
        release.write_release(entries, identity, output)


def test_review_plan_is_public_and_checks_actual_model(inputs, tmp_path):
    entries, identity = collect(inputs)
    result = release.prepare_release(entries, identity, tmp_path / "plan")
    content = Path(result["plan"]).read_text()
    assert "Someone" not in content and str(inputs[0]) not in content
    plan = json.loads(content)
    assert plan["model_id"] == "large-v3-q5_0"
    assert any(record["path"] == "Hisser.exe" for record in plan["files"])
    assert not list((tmp_path / "plan").glob("*.zip"))


def make_overlay(root):
    replacement = put(root, "msvcp140.dll", b"official redistribution library")
    put(root, "provenance.json", {
        "format_version": 1,
        "private_path": "C:\\Users\\Someone",
        "components": [{"name": "Microsoft VC runtime", "version": "14.5", "license": "Microsoft",
            "source_url": "https://aka.ms/vs/17/release/vc_redist.x64.exe", "source_sha256": "a" * 64,
            "source_hash_kind": "SHA-256 of the original DLL bytes in source_files order; not an archive hash",
            "source_files": ["msvcp140.dll"],
            "build_flags": []}],
        "files": [{"path": "msvcp140.dll", "size": replacement.stat().st_size,
                   "sha256": hashlib.sha256(replacement.read_bytes()).hexdigest()}],
    })
    return replacement


def test_overlay_replaces_both_runtime_and_python_crt_and_removes_private_fields(inputs, tmp_path):
    put(inputs[0], "_internal/MSVCP140.dll", b"old system library")
    overlay = tmp_path / "overlay"
    replacement = make_overlay(overlay)
    entries, _ = collect(inputs, runtime_overlay=overlay)
    overrides = [entry for entry in entries if entry.relative.lower().endswith("msvcp140.dll")]
    assert len(overrides) == 2
    assert all(entry.path == replacement and entry.expected_sha256 for entry in overrides)
    provenance = next(entry.content for entry in entries if entry.relative == "_internal/runtime/provenance.json")
    assert b"Microsoft VC runtime" in provenance
    assert b"not an archive hash" in provenance
    assert b"Someone" not in provenance


def test_overlay_requires_matching_inventory_and_source_integrity(inputs, tmp_path):
    overlay = tmp_path / "overlay"
    make_overlay(overlay)
    put(overlay, "unlisted.dll")
    with pytest.raises(release.ReleaseError, match="without public verification"):
        collect(inputs, runtime_overlay=overlay)


def test_overlay_binary_tampering_fails_before_publish(inputs, tmp_path):
    overlay = tmp_path / "overlay"
    replacement = make_overlay(overlay)
    entries, identity = collect(inputs, runtime_overlay=overlay)
    replacement.write_bytes(b"x" * replacement.stat().st_size)
    with pytest.raises(release.ReleaseError, match="SHA-256"):
        release.write_release(entries, identity, tmp_path / "release")
    assert not list((tmp_path / "release").iterdir())


def test_public_mode_cannot_accidentally_ship_original_personal_runtime(inputs):
    with pytest.raises(release.ReleaseError, match="complete reviewed"):
        collect(inputs, require_redistribution_overlay=True)
