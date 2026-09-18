"""מטא-דאטה נוספת לכל הקלטה (תגיות, הערות, משך) - נשמר כ-meta.json בתוך תיקיית ההקלטה."""
import json
from pathlib import Path

META_FILENAME = "meta.json"


def load_meta(meeting_dir: Path) -> dict:
    p = meeting_dir / META_FILENAME
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_meta(meeting_dir: Path, meta: dict) -> None:
    p = meeting_dir / META_FILENAME
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def update_meta(meeting_dir: Path, **kwargs) -> dict:
    meta = load_meta(meeting_dir)
    meta.update(kwargs)
    save_meta(meeting_dir, meta)
    return meta
