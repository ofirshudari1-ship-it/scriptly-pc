"""מרכז את כל המשימות שחולצו מהסיכומים של כל ההקלטות למסך אחד ('המשימות שלי') -
כדי שלא יהיה צריך לפתוח כל הקלטה בנפרד כדי לראות מה נשאר לעשות. מצב 'בוצע' נשמר
לכל הקלטה בנפרד ב-meta.json (לפי אינדקס המשימה בתוך אותה הקלטה)."""
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .meta import load_meta, update_meta

TASK_HEADER_VARIANTS = {"משימות ומעקב", "tasks & follow-ups"}


@dataclass
class Task:
    meeting_dir: Path
    meeting_title: str
    index: int
    text: str
    done: bool


def _extract_task_lines(summary: str) -> List[str]:
    in_tasks = False
    out = []
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_tasks = stripped.lstrip("#").strip().lower() in TASK_HEADER_VARIANTS
            continue
        if not in_tasks:
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            out.append(stripped[2:].strip())
    return out


def get_all_tasks(meetings) -> List[Task]:
    out = []
    for m in meetings:
        if not m.summary:
            continue
        meta = load_meta(m.dir)
        completed = set(meta.get("completed_tasks", []))
        for i, text in enumerate(_extract_task_lines(m.summary)):
            out.append(Task(meeting_dir=m.dir, meeting_title=m.title, index=i, text=text, done=i in completed))
    return out


def set_task_done(meeting_dir: Path, index: int, done: bool) -> None:
    meta = load_meta(meeting_dir)
    completed = set(meta.get("completed_tasks", []))
    if done:
        completed.add(index)
    else:
        completed.discard(index)
    update_meta(meeting_dir, completed_tasks=sorted(completed))
