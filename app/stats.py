"""סטטיסטיקה ותובנות על ההקלטות - לא נשלח לשום מקום, מחושב מקומית מהקבצים שכבר קיימים."""
from collections import Counter
from datetime import datetime, timedelta
from typing import List

from .meetings import Meeting

SPEAKER_YOU_VARIANTS = {"you", "אתה"}
SPEAKER_OTHER_VARIANTS = {"other side", "הצד השני"}


def compute_talk_ratio(meetings: List[Meeting]) -> dict:
    """יחס דיבור (את/ה מול הצד השני), לפי ספירת מילים תחת כל תיוג דובר בתמלול -
    קירוב סביר לזמן דיבור בפועל, בלי לדרוש שמירת timestamps מדויקים לכל מילה."""
    you_words = other_words = 0
    for m in meetings:
        if not m.transcript:
            continue
        current = None
        for line in m.transcript.splitlines():
            s = line.strip()
            if s.endswith(":") and s[:-1].strip().lower() in SPEAKER_YOU_VARIANTS:
                current = "you"
                continue
            if s.endswith(":") and s[:-1].strip().lower() in SPEAKER_OTHER_VARIANTS:
                current = "other"
                continue
            if not s or current is None:
                continue
            n = len(s.split())
            if current == "you":
                you_words += n
            else:
                other_words += n
    total = you_words + other_words
    if not total:
        return None
    return {
        "you_pct": round(100 * you_words / total),
        "other_pct": round(100 * other_words / total),
    }


def compute_daily_trend(meetings: List[Meeting], days: int = 14) -> List[int]:
    """כמות הקלטות ליום, ל-N הימים האחרונים (כולל היום) - מהישן לחדש."""
    today = datetime.now().date()
    counts = Counter(m.timestamp.date() for m in meetings)
    return [counts.get(today - timedelta(days=days - 1 - i), 0) for i in range(days)]


def compute_tone_breakdown(meetings: List[Meeting]) -> dict:
    counts = Counter(m.tone for m in meetings if m.tone)
    return {"positive": counts.get("positive", 0), "neutral": counts.get("neutral", 0), "tense": counts.get("tense", 0)}


def compute_top_tags(meetings: List[Meeting], limit: int = 5) -> List[tuple]:
    counter = Counter(tag for m in meetings for tag in m.tags)
    return counter.most_common(limit)


def compute_stats(meetings: List[Meeting]) -> dict:
    total = len(meetings)
    total_seconds = sum(m.duration_seconds for m in meetings)
    week_ago = datetime.now() - timedelta(days=7)
    this_week = sum(1 for m in meetings if m.timestamp >= week_ago)
    avg_seconds = (total_seconds / total) if total else 0

    day_counts = Counter(m.timestamp.strftime("%A") for m in meetings)
    busiest_day = day_counts.most_common(1)[0][0] if day_counts else None

    return {
        "total": total,
        "total_seconds": total_seconds,
        "this_week": this_week,
        "avg_seconds": avg_seconds,
        "busiest_day": busiest_day,
    }


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
