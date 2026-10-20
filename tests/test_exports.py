from __future__ import annotations

import copy
import html
import json
import pytest
from pypdf import PdfReader

from hisser import exports


@pytest.fixture
def transcript():
    return {
        "schema_version": 1, "source": "Aral ni José & Mañana <sample>.mp4",
        "language": "tl", "duration_ms": 1_815_678,
        "created_at": "2026-10-20T12:00:00+08:00", "engine": "synthetic QA fixture",
        "segments": [
            {"start_ms": 120, "end_ms": 2345, "text": "Magandang araw, José & Niño.\nKumusta <ka>?"},
            {"start_ms": 1_810_001, "end_ms": 1_815_678, "text": "Huling pangungusap pagkatapos ng minuto 30."},
        ],
        "text": "This stale summary must never become an export.",
    }


def test_all_formats_share_unicode_text_and_timings(tmp_path, transcript):
    before = copy.deepcopy(transcript)
    destinations = {kind: tmp_path / f"Mga salitâ ñ.{kind}" for kind in exports.FORMATS}
    assert exports.export_transcript(transcript, destinations) == list(destinations.values())
    canonical = json.loads(destinations["json"].read_text(encoding="utf-8"))
    assert canonical["text"] == "\n".join(segment["text"] for segment in transcript["segments"])
    assert destinations["txt"].read_text(encoding="utf-8").rstrip() == canonical["text"]
    for kind, separator in (("srt", ","), ("vtt", ".")):
        text = destinations[kind].read_text(encoding="utf-8")
        assert (text.startswith("WEBVTT\n\n")) == (kind == "vtt")
        for index, segment in enumerate(canonical["segments"], 1):
            assert f"{index}\n{exports.timestamp(segment['start_ms'], separator)} --> {exports.timestamp(segment['end_ms'], separator)}" in text
            assert segment["text"] in html.unescape(text)
        assert "00:30:10" in text
        assert "<ka>" not in text
    pdf = PdfReader(destinations["pdf"])
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "José & Niño" in text
    assert "Kumusta <ka>?" in text
    assert "Huling pangungusap" in text
    assert "00:30:10.001" in text
    fonts = pdf.pages[0]["/Resources"]["/Font"].get_object()
    # The Unicode face is embedded, rather than relying on a viewer's fonts.
    assert any("/FontDescriptor" in font.get_object()
               and "/FontFile2" in font.get_object()["/FontDescriptor"].get_object()
               for font in fonts.values())
    assert transcript == before
    assert not list(tmp_path.glob(".hisser-*"))


def test_overwrite_requires_explicit_opt_in(tmp_path, transcript):
    destination = tmp_path / "test.txt"
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        exports.export_transcript(transcript, {"txt": destination})
    assert destination.read_bytes() == b"original"
    exports.export_transcript(transcript, {"TXT": destination}, overwrite=True)
    assert "Magandang araw" in destination.read_text(encoding="utf-8")


def test_generation_failure_does_not_touch_any_destination(tmp_path, transcript, monkeypatch):
    existing = tmp_path / "test.txt"
    existing.write_bytes(b"keep original")
    new = tmp_path / "test.pdf"
    original = exports._generate

    def broken(canonical, kind, destination):
        if kind == "pdf":
            destination.write_bytes(b"partial pdf")
            raise OSError("Disk is full")
        original(canonical, kind, destination)

    monkeypatch.setattr(exports, "_generate", broken)
    with pytest.raises(OSError, match="Disk is full"):
        exports.export_transcript(transcript, {"txt": existing, "pdf": new}, overwrite=True)
    assert existing.read_bytes() == b"keep original"
    assert not new.exists()
    assert not list(tmp_path.glob(".hisser-*"))


def test_commit_failure_rolls_back_existing_and_new_files(tmp_path, transcript, monkeypatch):
    existing = tmp_path / "original.txt"
    existing.write_bytes(b"original bytes")
    fresh = tmp_path / "new.json"
    fail = tmp_path / "fail.vtt"
    original = exports._commit_file

    def broken(staged, destination, overwrite):
        if destination == fail:
            raise PermissionError("File is locked")
        original(staged, destination, overwrite)

    monkeypatch.setattr(exports, "_commit_file", broken)
    with pytest.raises(PermissionError, match="locked"):
        exports.export_transcript(transcript, {"txt": existing, "json": fresh, "vtt": fail}, overwrite=True)
    assert existing.read_bytes() == b"original bytes"
    assert not fresh.exists()
    assert not fail.exists()
    assert not list(tmp_path.glob(".hisser-*"))


@pytest.mark.parametrize("overwrite", [False, True])
def test_new_file_created_after_preflight_is_never_overwritten(tmp_path, transcript, monkeypatch, overwrite):
    destination = tmp_path / "race.txt"
    original = exports._generate

    def create_racer(canonical, kind, staged):
        original(canonical, kind, staged)
        destination.write_bytes(b"other program")

    monkeypatch.setattr(exports, "_generate", create_racer)
    with pytest.raises(FileExistsError):
        exports.export_transcript(transcript, {"txt": destination}, overwrite=overwrite)
    assert destination.read_bytes() == b"other program"
    assert not list(tmp_path.glob(".hisser-*"))


def test_new_file_appearing_during_commit_is_never_overwritten(tmp_path, transcript, monkeypatch):
    destination = tmp_path / "race.txt"
    original = exports._commit_file

    def create_racer(staged, target, overwrite):
        destination.write_bytes(b"other program during commit")
        original(staged, target, overwrite)

    monkeypatch.setattr(exports, "_commit_file", create_racer)
    with pytest.raises(FileExistsError):
        exports.export_transcript(transcript, {"txt": destination}, overwrite=True)
    assert destination.read_bytes() == b"other program during commit"
    assert not list(tmp_path.glob(".hisser-*"))


def test_preflight_cannot_expand_user_confirmed_overwrite_set(tmp_path, transcript):
    confirmed = tmp_path / "confirmed.txt"
    unconfirmed = tmp_path / "appeared.json"
    confirmed.write_bytes(b"original confirmed file")
    # This path appeared after the user confirmed a different file, before
    # the export worker got a chance to perform its own preflight.
    unconfirmed.write_bytes(b"new file from another program")
    with pytest.raises(FileExistsError, match="unconfirmed"):
        exports.export_transcript(transcript, {"txt": confirmed, "json": unconfirmed},
                                  overwrite=True, approved_overwrites={confirmed})
    assert confirmed.read_bytes() == b"original confirmed file"
    assert unconfirmed.read_bytes() == b"new file from another program"
    assert not list(tmp_path.glob(".hisser-*"))


def test_exact_confirmed_overwrite_paths_can_be_replaced(tmp_path, transcript):
    destination = tmp_path / "confirmed.txt"
    destination.write_bytes(b"old transcript")
    exports.export_transcript(transcript, {"txt": destination}, overwrite=True,
                              approved_overwrites={destination})
    assert "Magandang araw" in destination.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind,name", [("docx", "x.docx"), ("pdf", "source.mp4"), ("txt", "x.pdf")])
def test_reject_unsupported_formats_and_mismatched_extensions(tmp_path, transcript, kind, name):
    with pytest.raises(ValueError):
        exports.export_transcript(transcript, {kind: tmp_path / name})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("segment", [
    {"start_ms": -1, "end_ms": 4, "text": "bad"},
    {"start_ms": 4, "end_ms": 2, "text": "bad"},
    {"start_ms": 1.2, "end_ms": 4, "text": "bad"},
    {"start_ms": 1, "end_ms": 4, "text": "bad\x00"},
])
def test_bad_canonical_data_cannot_touch_outputs(tmp_path, transcript, segment):
    transcript["segments"] = [segment]
    with pytest.raises(ValueError):
        exports.export_transcript(transcript, {"txt": tmp_path / "result.txt"})
    assert not list(tmp_path.iterdir())


def test_duration_and_hour_timestamps():
    assert exports.timestamp(3_661_007) == "01:01:01,007"
    assert exports.timestamp(360_001_000, ".") == "100:00:01.000"


def test_empty_and_blank_text_are_valid(tmp_path, transcript):
    transcript["segments"] = []
    destinations = {kind: tmp_path / f"empty.{kind}" for kind in exports.FORMATS}
    exports.export_transcript(transcript, destinations)
    assert destinations["txt"].read_bytes() == b""
    assert destinations["vtt"].read_text(encoding="utf-8") == "WEBVTT\n\n"
    assert destinations["srt"].read_text(encoding="utf-8") == "\n\n"
    pdf = PdfReader(destinations["pdf"])
    assert "No speech was detected." in pdf.pages[0].extract_text()


def test_multipage_pdf_has_unicode_footer_and_complete_text(tmp_path, transcript):
    transcript["source"] = "Mahabang pangalan ng palabas - José at Niño - " * 4 + ".mp4"
    sentence = "José & Niño: Ang pag-aaral ay mahalaga. <Malinaw> ang salitâ at pananaw. "
    transcript["segments"] = [
        {"start_ms": index * 5000, "end_ms": (index + 1) * 5000,
         "text": f"SAMPLE {index + 1:03d}. " + sentence * (18 if index == 12 else 3)}
        for index in range(60)
    ]
    destination = tmp_path / "multi.pdf"
    exports.export_transcript(transcript, {"pdf": destination})
    pdf = PdfReader(destination)
    assert len(pdf.pages) >= 5
    all_text = "\n".join(page.extract_text() for page in pdf.pages)
    for index in range(60):
        assert f"SAMPLE {index + 1:03d}." in all_text
    for index, page in enumerate(pdf.pages, 1):
        text = page.extract_text()
        assert f"Page {index}" in text
        assert "SOURCE" in text
        assert "José" in text
        # Transform printable text origins into page coordinates. Detailed
        # glyph wrapping/clipping is also covered by rendered Poppler QA.
        anchors = []

        def collect_anchor(fragment, current, text_matrix, _font, size):
            if fragment.strip():
                x = text_matrix[4] * current[0] + text_matrix[5] * current[2] + current[4]
                y = text_matrix[4] * current[1] + text_matrix[5] * current[3] + current[5]
                anchors.append((x, y, size))

        page.extract_text(visitor_text=collect_anchor)
        assert anchors
        for x, y, size in anchors:
            assert float(page.mediabox.left) <= x < float(page.mediabox.right)
            assert float(page.mediabox.bottom) <= y < float(page.mediabox.top)
            assert size > 0
