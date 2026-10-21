"""Download verification rejects tampering and unsafe extraction before execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
import zipfile

import pytest

from test_release import inputs, collect, release

SPEC = importlib.util.spec_from_file_location(
    "verify_release", Path(__file__).resolve().parents[1] / "scripts/verify-release.py")
verify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify
SPEC.loader.exec_module(verify)


@pytest.fixture
def candidate(inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "MODELS", {inputs[3].id: inputs[3]})
    (inputs[2] / "upstream.txt").write_text(
        "Source: https://static.crates.io/crates/home/home-0.5.11.crate\n"
        "Notice: rav1e-crates/home/LICENSE-MIT.txt\n", encoding="utf-8")
    entries, identity = collect(inputs)
    result = release.write_release(entries, identity, tmp_path / "candidate")
    return Path(result["archive"]), result["sha256"]


def rewrite_zip(candidate, tmp_path, *, extra=None, transform=None):
    original, _ = candidate
    output = tmp_path / "modified.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info)
            if transform:
                content = transform(info.filename, content)
            target.writestr(info, content)
        if extra:
            target.writestr(*extra)
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


def test_verified_archive_extracts_exact_manifest_in_unicode_fresh_folder(candidate, tmp_path):
    output = tmp_path / "José & Niño"
    result = verify.verify_archive(*candidate, output)
    assert result["verified"] and result["model_id"] == "large-v3-q5_0"
    assert (output / "Hisser/Hisser.exe").is_file()
    assert (output / "Hisser/release-manifest.json").is_file()
    assert not (output / "Hisser/data/settings.json").exists()


def test_wrong_download_checksum_prevents_extraction(candidate, tmp_path):
    output = tmp_path / "untrusted"
    with pytest.raises(verify.VerificationError, match="ZIP SHA-256"):
        verify.verify_archive(candidate[0], "0" * 64, output)
    assert not output.exists()


def test_manifest_hash_detects_changed_payload_even_if_zip_hash_is_updated(candidate, tmp_path):
    changed = rewrite_zip(candidate, tmp_path,
                          transform=lambda name, content: b"changed" if name == "Hisser/Hisser.exe" else content)
    with pytest.raises(verify.VerificationError, match="size differs|checksum differs"):
        verify.verify_archive(*changed)


@pytest.mark.parametrize("name", ["../escape.txt", "Hisser/../escape.txt", "Hisser/C:/escape.txt", "Hisser/CON.txt"])
def test_unsafe_names_cannot_escape_extraction(candidate, tmp_path, name):
    changed = rewrite_zip(candidate, tmp_path, extra=(name, b"unsafe"))
    with pytest.raises(verify.packaging.ReleaseError, match="Unsafe archive entry"):
        verify.verify_archive(*changed, tmp_path / "extraction")
    assert not (tmp_path / "extraction").exists()


def test_extra_entry_not_in_manifest_is_rejected(candidate, tmp_path):
    changed = rewrite_zip(candidate, tmp_path, extra=("Hisser/private-notes.txt", b"private"))
    with pytest.raises(verify.VerificationError, match="inventories differ"):
        verify.verify_archive(*changed)


def test_manifest_cannot_authorize_an_extra_private_file(candidate, tmp_path):
    private = b"private working notes"
    def authorize_extra(name, content):
        if name == "Hisser/release-manifest.json":
            manifest = json.loads(content)
            manifest["files"].append({"path": "private-notes.txt", "size": len(private),
                                      "sha256": hashlib.sha256(private).hexdigest()})
            return json.dumps(manifest).encode("utf-8")
        return content
    changed = rewrite_zip(candidate, tmp_path, extra=("Hisser/private-notes.txt", private), transform=authorize_extra)
    with pytest.raises(verify.VerificationError, match="Unrecognized public release file"):
        verify.verify_archive(*changed)


def test_link_entries_are_rejected_without_creating_files(candidate, tmp_path):
    info = zipfile.ZipInfo("Hisser/link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    changed = rewrite_zip(candidate, tmp_path, extra=(info, b"../../private"))
    with pytest.raises(verify.VerificationError, match="Linked or special"):
        verify.verify_archive(*changed)


def test_existing_destination_is_never_overwritten(candidate, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    original = output / "keep.txt"
    original.write_text("keep")
    with pytest.raises(verify.VerificationError, match="fresh output"):
        verify.verify_archive(*candidate, output)
    assert original.read_text() == "keep"


def test_clean_subprocess_environment_does_not_depend_on_developer_tools(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\developer\python;C:\developer\ffmpeg")
    monkeypatch.setenv("PYTHONPATH", r"C:\private\source")
    monkeypatch.setenv("CUDA_PATH", r"C:\developer\cuda")
    monkeypatch.setenv("HISSER_PDF_FONT", r"C:\private\font.ttf")
    monkeypatch.setenv("VIRTUAL_ENV", r"C:\developer\venv")
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    env = verify.clean_windows_environment()
    assert "developer" not in env["PATH"]
    assert all(name not in env for name in ("PYTHONPATH", "CUDA_PATH", "HISSER_PDF_FONT", "VIRTUAL_ENV"))
