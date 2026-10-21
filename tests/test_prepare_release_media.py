"""Public media selection must not smuggle unreviewed files into a release."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "prepare_release_media", Path(__file__).resolve().parents[1] / "scripts" / "prepare-release-media.py")
media = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = media
SPEC.loader.exec_module(media)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def record(relative, content):
    return {"path": relative, "size": len(content), "sha256": digest(content)}


def put(root, relative, content):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


@pytest.fixture
def inputs(tmp_path):
    base = tmp_path / "licensed-REDIST"
    original_order = ["msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll"]
    originals = {name: ("licensed " + name).encode() for name in original_order}
    records = []
    for name, content in originals.items():
        for relative in (name, "cuda/" + name):
            put(base, relative, content)
            records.append(record(relative, content))
    # Old, reviewed media may be present in the base but must be replaced.
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        content = ("old " + name).encode()
        put(base, name, content)
        records.append(record(name, content))
    microsoft = {"name": media.MICROSOFT_COMPONENT, "version": "14.51.36231",
                 "source_url": "https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution",
                 "source_sha256": digest(b"".join(originals.values())),
                 "source_hash_kind": "SHA-256 of the concatenated original DLL bytes in source_files order; not an archive hash",
                 "source_files": original_order,
                 "license": "Microsoft Visual Studio 2026 license and REDIST list", "build_flags": []}
    put(base, "provenance.json", media.release.json_bytes({
        "format_version": 1, "components": [microsoft], "files": records}))
    archive = tmp_path / "upstream.zip"
    files = []
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            content = ("new pinned " + name).encode()
            member = "upstream/bin/" + name
            bundle.writestr(member, content)
            files.append(dict(record(name, content), archive_path=member))
        bundle.writestr("upstream/doc/do-not-copy.txt", b"unselected upstream documentation")
        bundle.writestr("upstream/bin/ffplay.exe", b"unselected program")
    manifest = {"format_version": 1, "binary_archive": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/pinned/upstream.zip",
        "size": archive.stat().st_size, "sha256": media.sha256(archive)}, "files": files,
        "components": [{"name": "FFmpeg", "version": "pinned", "license": "LGPL-3.0-or-later",
                        "source_url": "https://example.com/ffmpeg-source.tar.gz",
                        "source_sha256": "a" * 64, "build_flags": ["--disable-gpl"]}]}
    return base, archive, manifest, tmp_path / "prepared"


def prepare(inputs):
    base, archive, manifest, output = inputs
    return media.prepare(base, output, archive, manifest=manifest)


def test_only_pinned_media_and_original_microsoft_files_enter_overlay(inputs):
    report = prepare(inputs)
    base, _, manifest, output = inputs
    expected = media.release.MSVC_NAMES | {"cuda/" + name for name in media.release.MSVC_NAMES}
    actual, components = media.release.load_overlay(output)
    assert actual.keys() == expected | {"ffmpeg.exe", "ffprobe.exe"}
    assert report["files"] == 10
    assert components[0]["name"] == media.MICROSOFT_COMPONENT
    assert components[1] == manifest["components"][0]
    for name in expected:
        assert (output / name).read_bytes() == (base / name).read_bytes()
    assert (output / "ffmpeg.exe").read_bytes() == b"new pinned ffmpeg.exe"
    assert (base / "ffmpeg.exe").read_bytes() == b"old ffmpeg.exe"


def test_archive_tampering_is_rejected_before_output(inputs):
    inputs[1].write_bytes(b"tampered upstream bytes")
    with pytest.raises(media.release.ReleaseError, match="Size or SHA-256"):
        prepare(inputs)
    assert not inputs[3].exists()


def test_pinned_executable_hash_is_independent_of_archive_hash(inputs):
    inputs[2]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(media.release.ReleaseError, match="executable SHA-256"):
        prepare(inputs)
    assert not inputs[3].exists()


def test_same_size_microsoft_tampering_is_rejected(inputs):
    path = inputs[0] / "msvcp140.dll"
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(media.release.ReleaseError, match="Base overlay SHA-256"):
        prepare(inputs)
    assert not inputs[3].exists()


def test_unlisted_base_file_cannot_be_ignored(inputs):
    put(inputs[0], "unexpected.dll", b"unreviewed")
    with pytest.raises(media.release.ReleaseError, match="without public verification"):
        prepare(inputs)


@pytest.mark.parametrize("member", ["../private.txt", "upstream/bin/FFMPEG.EXE"])
def test_even_unselected_unsafe_or_ambiguous_archive_paths_are_rejected(inputs, member):
    _, archive, manifest, output = inputs
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr(member, b"unselected payload")
    manifest["binary_archive"].update(size=archive.stat().st_size, sha256=media.sha256(archive))
    with pytest.raises(media.release.ReleaseError, match="Unsafe archive|duplicate paths"):
        prepare(inputs)
    assert not output.exists()


def test_existing_output_is_never_overwritten(inputs):
    output = inputs[3]
    output.mkdir()
    put(output, "keep.txt", b"preserve")
    with pytest.raises(media.release.ReleaseError, match="fresh output"):
        prepare(inputs)
    assert (output / "keep.txt").read_bytes() == b"preserve"


def test_output_cannot_change_the_verified_base_inventory(inputs):
    base, archive, manifest, _ = inputs
    with pytest.raises(media.release.ReleaseError, match="outside the base overlay"):
        media.prepare(base, base / "new-output", archive, manifest=manifest)
    assert not (base / "new-output").exists()


def test_committed_media_pin_records_source_and_binary_archives():
    manifest = media.load_manifest()
    assert {item["path"] for item in manifest["files"]} == {"ffmpeg.exe", "ffprobe.exe"}
    kinds = [component.get("source_hash_kind", "") for component in manifest["components"]]
    assert any("binary ZIP archive" in kind for kind in kinds)
    assert any("FFmpeg build recipes" in component["name"] for component in manifest["components"])
