"""Local exports from a single canonical, timed transcript.

Generation finishes in temporary sibling files before any destination is touched.
Existing files are backed up for rollback when replacing a set of exports.
"""

from __future__ import annotations

from collections.abc import Collection
import html
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any


FORMATS = ("pdf", "srt", "txt", "vtt", "json")
_FONT_LOCK = threading.RLock()


class ExportError(RuntimeError):
    """An export could not be committed safely."""


def _milliseconds(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer in milliseconds.")
    return value


def _canonical(transcript: dict) -> dict:
    if not isinstance(transcript, dict) or transcript.get("schema_version") != 1:
        raise ValueError("Unsupported transcript schema; expected schema_version 1.")
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Transcript segments must be a list.")
    normalized = []
    last_start = -1
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"Segment {index + 1} must be an object.")
        start = _milliseconds(segment.get("start_ms"), "Segment start")
        end = _milliseconds(segment.get("end_ms"), "Segment end")
        if end < start or start < last_start:
            raise ValueError("Transcript segments must have ordered, valid timings.")
        text = segment.get("text")
        if not isinstance(text, str) or "\x00" in text:
            raise ValueError("Each transcript segment needs text without null characters.")
        # Blank lines inside a subtitle are cue delimiters. Normalize them once,
        # identically for every format, so each export represents the same text.
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        normalized.append({"start_ms": start, "end_ms": end, "text": text})
        last_start = start
    duration = _milliseconds(transcript.get("duration_ms"), "Transcript duration")
    if normalized and max(segment["end_ms"] for segment in normalized) > duration:
        raise ValueError("A segment ends after the transcript duration.")
    source = transcript.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Transcript source must be a non-empty filename.")
    result = dict(transcript)
    result.update(segments=normalized, text="\n".join(s["text"] for s in normalized if s["text"]))
    return result


def timestamp(milliseconds: int, separator: str = ",") -> str:
    """Format complete subtitle timestamps, including speech after an hour."""
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}"


def _subtitle(transcript: dict, webvtt: bool) -> str:
    blocks = ["WEBVTT"] if webvtt else []
    separator = "." if webvtt else ","
    for number, segment in enumerate(transcript["segments"], 1):
        if not segment["text"]:
            continue
        timing = f"{timestamp(segment['start_ms'], separator)} --> {timestamp(segment['end_ms'], separator)}"
        # Subtitle players interpret angle brackets and ampersands as markup.
        text = html.escape(segment["text"], quote=False)
        blocks.append(f"{number}\n{timing}\n{text}")
    return "\n\n".join(blocks) + "\n\n"


def _font_names() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    with _FONT_LOCK:
        if "HisserRegular" in pdfmetrics.getRegisteredFontNames():
            return "HisserRegular", "HisserBold"
        windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates = []
        override = os.environ.get("HISSER_PDF_FONT")
        if override:
            candidates.append((Path(override), Path(os.environ.get("HISSER_PDF_FONT_BOLD", override))))
        candidates += [
            (windows_fonts / "segoeui.ttf", windows_fonts / "segoeuib.ttf"),
            (windows_fonts / "arial.ttf", windows_fonts / "arialbd.ttf"),
            (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
            (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
             Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
        ]
        for regular, bold in candidates:
            if regular.is_file():
                pdfmetrics.registerFont(TTFont("HisserRegular", str(regular)))
                pdfmetrics.registerFont(TTFont("HisserBold", str(bold if bold.is_file() else regular)))
                pdfmetrics.registerFontFamily("Hisser", normal="HisserRegular", bold="HisserBold")
                return "HisserRegular", "HisserBold"
    raise ExportError("A Unicode PDF font was not found. Restore Windows Segoe UI or set HISSER_PDF_FONT to a Unicode TTF font.")


def _pdf(transcript: dict, destination: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    regular, bold = _font_names()
    page_width, page_height = A4
    margin = 20 * mm
    width = page_width - 2 * margin
    source_style = ParagraphStyle("Source", fontName=regular, fontSize=8, leading=11,
                                  textColor=colors.HexColor("#5b616a"), splitLongWords=True)
    source = Paragraph("SOURCE  " + html.escape(transcript["source"]), source_style)
    _, source_height = source.wrap(width, page_height)
    top_margin = margin + source_height + 9 * mm
    doc = SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=top_margin, bottomMargin=20 * mm,
                            title=f"Transcript - {transcript['source']}", author="Hisser")
    title_style = ParagraphStyle("Title", fontName=bold, fontSize=24, leading=29,
                                textColor=colors.HexColor("#171a1f"), spaceAfter=8)
    detail_style = ParagraphStyle("Details", fontName=regular, fontSize=9, leading=13,
                                 textColor=colors.HexColor("#5b616a"), spaceAfter=18)
    timing_style = ParagraphStyle("Timing", fontName=regular, fontSize=8, leading=11,
                                 textColor=colors.HexColor("#59636d"), keepWithNext=True, spaceAfter=3)
    text_style = ParagraphStyle("Speech", fontName=regular, fontSize=10.5, leading=15.5,
                               alignment=TA_LEFT, textColor=colors.HexColor("#20252b"),
                               spaceAfter=13, splitLongWords=True, allowWidows=0, allowOrphans=0)

    def decorate(canvas, document):
        canvas.saveState()
        source.drawOn(canvas, margin, page_height - margin - source_height)
        canvas.setStrokeColor(colors.HexColor("#d9dfe4"))
        canvas.setLineWidth(0.5)
        canvas.line(margin, 16 * mm, page_width - margin, 16 * mm)
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#5b616a"))
        canvas.drawString(margin, 11 * mm, "Hisser | Transcript")
        canvas.drawRightString(page_width - margin, 11 * mm, f"Page {document.page}")
        canvas.restoreState()

    language = transcript.get("language") or "Detected automatically"
    details = f"Language: {html.escape(str(language))}  |  Duration: {timestamp(transcript['duration_ms'], '.')}"
    story = [Paragraph("Transcript", title_style), Paragraph(details, detail_style)]
    for segment in transcript["segments"]:
        if not segment["text"]:
            continue
        label = f"{timestamp(segment['start_ms'], '.')} - {timestamp(segment['end_ms'], '.')}"
        story.append(Paragraph(label, timing_style))
        escaped = html.escape(segment["text"]).replace("\t", "    ").replace("\n", "<br/>")
        story.append(Paragraph(escaped, text_style))
    if not any(segment["text"] for segment in transcript["segments"]):
        story.append(Paragraph("No speech was detected.", text_style))
    story.append(Spacer(1, 1))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)


def _generate(transcript: dict, format_name: str, destination: Path) -> None:
    if format_name == "pdf":
        _pdf(transcript, destination)
    elif format_name == "json":
        destination.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif format_name == "txt":
        destination.write_text(transcript["text"] + ("\n" if transcript["text"] else ""), encoding="utf-8")
    else:
        destination.write_text(_subtitle(transcript, format_name == "vtt"), encoding="utf-8")


def _temporary_sibling(destination: Path, label: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".hisser-{label}-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    return Path(name)


def _commit_file(staged: Path, destination: Path, overwrite: bool) -> None:
    if overwrite:
        os.replace(staged, destination)
    elif os.name == "nt":
        # Windows rename refuses to replace a destination created since preflight.
        os.rename(staged, destination)
    else:
        # POSIX rename would silently replace an existing file.
        os.link(staged, destination)
        staged.unlink()


def export_transcript(transcript: dict, destinations: dict[str, Path], overwrite: bool = False,
                      *, approved_overwrites: Collection[Path] | None = None) -> list[Path]:
    """Generate selected formats without recognition, then commit the whole set.

    The caller obtains destination paths with native dialogs and confirms existing
    files before opting into ``overwrite``. ``approved_overwrites`` limits that
    permission to the exact paths confirmed by the user, even if another file
    appears before this worker starts. The original transcript is untouched.
    """
    canonical = _canonical(transcript)
    if not isinstance(destinations, dict) or not destinations:
        raise ValueError("Select at least one export format.")
    requested = []
    seen_paths = set()
    seen_formats = set()
    approved_existing: set[Path] = set()
    confirmed_paths = (None if approved_overwrites is None else
                       {os.path.normcase(str(Path(path).expanduser().resolve())) for path in approved_overwrites})
    for key, path in destinations.items():
        if not isinstance(key, str) or key.lower() not in FORMATS:
            raise ValueError(f"Unsupported export format: {key!r}")
        format_name = key.lower()
        if format_name in seen_formats:
            raise ValueError(f"Export format was selected twice: {format_name}")
        destination = Path(path).expanduser().absolute()
        if destination.suffix.lower() != f".{format_name}":
            raise ValueError(f"The {format_name.upper()} filename must end in .{format_name}.")
        identity = os.path.normcase(str(destination.resolve()))
        if identity in seen_paths:
            raise ValueError("Two exports cannot use the same destination.")
        if not destination.parent.is_dir():
            raise FileNotFoundError(f"Export folder does not exist: {destination.parent}")
        if destination.is_symlink() or destination.is_dir():
            raise ValueError(f"Choose a regular output file: {destination}")
        if destination.exists():
            if not destination.is_file():
                raise ValueError(f"Choose a regular output file: {destination}")
            if not overwrite:
                raise FileExistsError(f"Export already exists: {destination}")
            if confirmed_paths is not None and identity not in confirmed_paths:
                raise FileExistsError(f"An unconfirmed export already exists. Choose the destination again: {destination}")
            approved_existing.add(destination)
        seen_paths.add(identity)
        seen_formats.add(format_name)
        requested.append((format_name, destination))

    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    preserve_backups: set[Path] = set()
    try:
        for format_name, destination in requested:
            temporary = _temporary_sibling(destination, "export")
            staged[destination] = temporary
            _generate(canonical, format_name, temporary)
        # Make every backup before replacing anything. A disk-full/permission
        # error during backup creation therefore leaves all originals untouched.
        for _, destination in requested:
            if destination in approved_existing:
                if destination.is_symlink() or not destination.is_file():
                    raise FileNotFoundError(f"An existing export changed during generation. Choose the destination again: {destination}")
                backup = _temporary_sibling(destination, "backup")
                backups[destination] = backup
                shutil.copy2(destination, backup)
            elif destination.exists() or destination.is_symlink():
                # overwrite=True authorizes only files present during preflight.
                # A file created by somebody else while generating is unapproved.
                raise FileExistsError(f"An export appeared during generation. Choose the destination again: {destination}")
        try:
            for _, destination in requested:
                _commit_file(staged[destination], destination, destination in approved_existing)
                committed.append(destination)
        except BaseException as failure:
            rollback_failures = []
            for destination in reversed(committed):
                try:
                    if destination in backups:
                        os.replace(backups[destination], destination)
                    else:
                        destination.unlink(missing_ok=True)
                except OSError:
                    if destination in backups:
                        preserve_backups.add(backups[destination])
                    rollback_failures.append(str(destination))
            if rollback_failures:
                saved = ", ".join(str(path) for path in preserve_backups)
                raise ExportError(f"Export failed and some files could not be restored. Original backups: {saved}. Affected files: {', '.join(rollback_failures)}") from failure
            raise
    finally:
        for temporary in [*staged.values(), *backups.values()]:
            if temporary not in preserve_backups:
                temporary.unlink(missing_ok=True)
    return [destination for _, destination in requested]
