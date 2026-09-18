"""סריקת תיקיית הפגישות ובניית רשימת פגישות לתצוגה בדשבורד."""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List

from .i18n import t
from .meta import load_meta

# Below this words-per-minute rate we treat a recording as "probably not an actual
# conversation" (background noise/silence that VAD still let through) rather than a
# meeting - a purely local heuristic (word count vs. duration), no cloud call. See
# Meeting.likely_noise below and CHANGELOG.md for the competitor research this responds to.
NOISE_WPM_THRESHOLD = 5.0
# Recordings shorter than this are never flagged - too little signal either way, and
# short test recordings shouldn't get badged as "noise".
NOISE_MIN_DURATION_SECONDS = 25.0


@dataclass
class Meeting:
    dir: Path
    timestamp: datetime
    summary: str
    transcript: str
    has_audio: bool
    is_processing: bool = False
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    duration_seconds: float = 0.0
    ai_title: str = ""
    tone: str = ""
    segments: List[dict] = field(default_factory=list)

    @property
    def has_summary(self) -> bool:
        return bool(self.summary)

    @property
    def datetime_label(self) -> str:
        return self.timestamp.strftime("%d/%m/%Y %H:%M")

    @property
    def title(self) -> str:
        return self.ai_title or self.datetime_label

    @property
    def duration_label(self) -> str:
        total = int(self.duration_seconds)
        return f"{total // 60}:{total % 60:02d}" if total else ""

    @property
    def preview(self) -> str:
        for line in self.summary.splitlines():
            line = line.strip("# ").strip()
            if line:
                return line[:80]
        return t("processing_marker") if self.is_processing else t("no_summary")

    @property
    def searchable_text(self) -> str:
        return " ".join([self.title, self.preview, self.summary, self.transcript, self.notes, " ".join(self.tags)]).lower()

    @property
    def likely_noise(self) -> bool:
        """True when this recording is long enough to almost certainly contain a real
        conversation, yet produced far too little transcribed speech - background
        noise, a muted call, or silence that the recorder's VAD still let through.
        Local-only heuristic (word count / duration), no AI call - used to let the
        dashboard hide clutter from a growing recordings list on request."""
        if self.is_processing or not self.transcript:
            return False
        if self.duration_seconds < NOISE_MIN_DURATION_SECONDS:
            return False
        word_count = len(self.transcript.split())
        words_per_minute = word_count / (self.duration_seconds / 60)
        return words_per_minute < NOISE_WPM_THRESHOLD


def list_meetings(meetings_dir: Path) -> List[Meeting]:
    meetings = []
    if not meetings_dir.exists():
        return meetings
    for d in sorted(meetings_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        try:
            ts = datetime.strptime(d.name, "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            continue
        summary_path = d / "summary.md"
        transcript_path = d / "transcript.txt"
        summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
        transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
        has_audio = (d / "recording.wav").exists()
        is_processing = not summary_path.exists()
        meta = load_meta(d)
        segments_path = d / "segments.json"
        segments = []
        if segments_path.exists():
            try:
                segments = json.loads(segments_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                segments = []
        meetings.append(
            Meeting(
                dir=d,
                timestamp=ts,
                summary=summary,
                transcript=transcript,
                has_audio=has_audio,
                is_processing=is_processing,
                tags=meta.get("tags", []),
                notes=meta.get("notes", ""),
                duration_seconds=meta.get("duration_seconds", 0.0),
                ai_title=meta.get("ai_title", ""),
                tone=meta.get("tone", ""),
                segments=segments,
            )
        )
    return meetings
