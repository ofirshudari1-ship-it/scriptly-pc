"""הלוגיקה המרכזית של Scriptly - מפריד בין ה-UI (דשבורד/מגש/overlay) לבין ההקלטה/תמלול/סיכום.

גם הדשבורד וגם אייקון המגש קוראים לאותו controller, כדי שלא יהיו שני מקורות אמת
למצב ההקלטה (זה בדיוק מה שקרה כשכמה עותקים של האפליקציה רצו יחד).
"""
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from .audio_capture import MeetingRecorder
from .config import load_config
from .i18n import t
from .logger import get_logger
from .meetings import list_meetings
from .meta import load_meta, update_meta
from .summarize import MIN_WORDS_FOR_SUMMARY, generate_tags, generate_title, generate_tone, summarize
from .tasks import get_all_tasks, set_task_done
from .transcribe import transcribe_segments
from .voice_commands import VoiceCommandListener

logger = get_logger(__name__)

# Fallback only for the (very unlikely) case the config key is missing entirely -
# the real value the app uses is config["min_recording_duration"] (see stop_recording()
# below). This used to be a hardcoded 1.5s constant that silently ignored the
# "min_recording_duration" default already declared in config.py's DEFAULTS (5s) -
# a config value nothing ever read, so changing it (had there been a settings UI
# field for it) would have done nothing. Fixed: the config value is now the single
# source of truth, and a settings field was added (app/dashboard.py, open_settings).
MIN_RECORDING_SECONDS_FALLBACK = 5


def _label_segments(segments: list, timeline_path: Path) -> str:
    """ממזג קטעי תמלול עם ציר הזמן שנמדד בזמן ההקלטה (מיקרופון מול אודיו מערכת),
    ומתייג כל קטע כ"אתה" / "הצד השני" - זיהוי דוברים פשוט בלי מודל נפרד."""
    plain = "\n".join(s["text"] for s in segments)
    if not timeline_path.exists():
        return plain
    try:
        data = json.loads(timeline_path.read_text(encoding="utf-8"))
        chunk_seconds = data["chunk_seconds"]
        labels = data["labels"]
    except (json.JSONDecodeError, OSError, KeyError):
        return plain

    display = {"you": t("speaker_you"), "other": t("speaker_other")}
    lines = []
    last_speaker = None
    for seg in segments:
        start_idx = int(seg["start"] / chunk_seconds)
        end_idx = max(start_idx + 1, int(seg["end"] / chunk_seconds))
        window = labels[start_idx:end_idx] if start_idx < len(labels) else []
        counts = {"you": window.count("you"), "other": window.count("other")}
        if counts["you"] == 0 and counts["other"] == 0:
            speaker = last_speaker
        else:
            speaker = "you" if counts["you"] >= counts["other"] else "other"
        if speaker and speaker != last_speaker:
            lines.append(f"\n{display[speaker]}:")
            last_speaker = speaker
        lines.append(seg["text"])
    return "\n".join(lines).strip()


class AppController:
    def __init__(self):
        self.config = load_config()
        self.recorder = MeetingRecorder()
        self._listeners = []
        self._record_start_time = None
        self.voice_listener = VoiceCommandListener(on_trigger=self._on_voice_trigger, get_config=lambda: self.config)

    def add_listener(self, callback):
        """callback(event: str, payload: dict) - עשוי להיקרא מכל thread."""
        self._listeners.append(callback)

    def notify_event(self, event, payload=None):
        """נקודת כניסה ציבורית ל-UI events שאינם קשורים למצב הקלטה עצמו (למשל
        התראת "רץ ברקע" חד-פעמית) - כדי שרכיבי UI לא יקראו ל-_emit הפרטי ישירות."""
        self._emit(event, **(payload or {}))

    def _emit(self, event, **payload):
        for cb in list(self._listeners):
            try:
                cb(event, payload)
            except Exception:
                logger.exception("listener error for event %s", event)

    def reload_config(self):
        self.config = load_config()
        self._emit("config_reloaded")

    @property
    def is_recording(self) -> bool:
        return self.recorder.is_recording

    @property
    def meetings_dir(self) -> Path:
        return Path(self.config["meetings_dir"])

    def toggle_recording(self):
        if self.recorder.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    @property
    def voice_armed(self) -> bool:
        return self.voice_listener.is_armed

    def arm_voice_command(self, duration_seconds: int = 60):
        """מפעיל האזנה לפקודה קולית (60 שניות כברירת מחדל): 'תתחיל הקלטה' אם אין הקלטה
        פעילה כרגע, או 'עצור הקלטה' אם יש. כבוי אוטומטית אחרי הזמן הזה, גם בלי לזהות כלום."""
        if not self.config.get("voice_commands", False) or self.voice_listener.is_armed:
            return
        mode = "stop" if self.recorder.is_recording else "start"
        self._emit("voice_armed", mode=mode)
        self.voice_listener.arm(mode, duration_seconds, on_disarmed=lambda: self._emit("voice_disarmed"))

    def disarm_voice_command(self):
        self.voice_listener.disarm()

    def _on_voice_trigger(self, mode: str):
        if mode == "start":
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.recorder.is_recording:
            return
        max_gb = self.config.get("max_file_size_gb", 10)
        # None/0/negative = no cap, rather than treating it as "stop after 0 bytes" -
        # max_file_size_gb used to be a declared config default nothing ever read
        # (see audio_capture.MeetingRecorder.start's docstring), so a very long,
        # accidentally-left-running recording could grow its in-memory buffer until
        # the whole app crashed with no warning and the recording was lost entirely.
        max_bytes = int(max_gb * (1024 ** 3)) if max_gb and max_gb > 0 else None
        try:
            self.recorder.start(
                mic_device_index=self.config.get("mic_device_index"),
                max_bytes=max_bytes,
                on_size_limit=self._on_recording_size_limit,
            )
        except Exception as exc:
            logger.error("failed to start recording: %s", exc)
            self._emit("error", message=t("error_start_recording", exc=exc))
            return
        self._record_start_time = datetime.now()
        self._emit("recording_started")

    def _on_recording_size_limit(self):
        """Called from MeetingRecorder on its own background thread when a recording
        auto-stops after hitting max_file_size_gb - finalizes and saves the recording
        immediately (same as a normal stop) rather than leaving the UI showing "still
        recording" while capture has actually already stopped in the background."""
        logger.info("recording hit its configured size limit - finalizing now")
        self.stop_recording(size_limit_hit=True)

    def stop_recording(self, size_limit_hit: bool = False):
        if not self.recorder.is_recording:
            return
        started_at = self._record_start_time
        timestamp = (started_at or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
        meeting_dir = self.meetings_dir / timestamp
        wav_path = meeting_dir / "recording.wav"
        try:
            self.recorder.stop(wav_path)
        except Exception as exc:
            logger.error("failed to stop recording: %s", exc)
            self._emit("error", message=t("error_stop_recording", exc=exc))
            return

        duration = (datetime.now() - started_at).total_seconds() if started_at else 0.0
        self._emit("recording_stopped", meeting_dir=meeting_dir)
        if size_limit_hit:
            self._emit("recording_size_limit_reached", meeting_dir=meeting_dir)

        min_seconds = self.config.get("min_recording_duration", MIN_RECORDING_SECONDS_FALLBACK)
        if duration < min_seconds:
            logger.info("discarding too-short recording (%.1fs)", duration)
            try:
                wav_path.unlink(missing_ok=True)
                (meeting_dir / "speaker_timeline.json").unlink(missing_ok=True)
                meeting_dir.rmdir()
            except OSError:
                pass
            self._emit("recording_discarded", reason="too_short")
            return

        update_meta(meeting_dir, duration_seconds=duration)

        if self.config.get("auto_summarize", True):
            self.summarize_meeting(meeting_dir)
        else:
            logger.info("auto-summarize is off - leaving %s pending", meeting_dir)
            self._emit("recording_saved_pending", meeting_dir=meeting_dir)

    def delete_meeting(self, meeting_dir: Path):
        """מוחק לצמיתות הקלטה (תיקייה שלמה: אודיו/תמלול/סיכום)."""
        try:
            shutil.rmtree(meeting_dir, ignore_errors=True)
            self._emit("meeting_deleted", meeting_dir=meeting_dir)
        except Exception as exc:
            logger.error("failed to delete %s: %s", meeting_dir, exc)
            self._emit("error", message=t("error_processing", exc=exc))

    def update_meeting_meta(self, meeting_dir: Path, **kwargs):
        update_meta(meeting_dir, **kwargs)
        self._emit("meeting_meta_updated", meeting_dir=meeting_dir)

    def get_all_tasks(self):
        """כל המשימות שחולצו מכל ההקלטות, למסך 'המשימות שלי' המרוכז."""
        return get_all_tasks(list_meetings(self.meetings_dir))

    def set_task_done(self, meeting_dir: Path, index: int, done: bool):
        set_task_done(meeting_dir, index, done)
        self._emit("task_updated", meeting_dir=meeting_dir)

    def summarize_meeting(self, meeting_dir: Path):
        """מפעיל תמלול+סיכום לפגישה קיימת (רץ אוטומטית, או ידנית דרך כפתור 'סכם עכשיו')."""
        wav_path = meeting_dir / "recording.wav"
        if not wav_path.exists():
            self._emit("error", message=t("error_processing", exc="recording.wav not found"))
            return
        threading.Thread(target=self._process_meeting, args=(wav_path, meeting_dir), daemon=True).start()

    def _process_meeting(self, wav_path: Path, meeting_dir: Path):
        self._emit("processing_started", meeting_dir=meeting_dir)
        try:
            segments = transcribe_segments(
                wav_path,
                self.config["whisper_model"],
                self.config["whisper_device"],
                self.config["whisper_compute_type"],
                self.config["language"],
                hotwords=self.config.get("custom_vocabulary", ""),
            )
            timeline_path = meeting_dir / "speaker_timeline.json"
            if self.config.get("speaker_labels", True):
                transcript = _label_segments(segments, timeline_path)
            else:
                transcript = "\n".join(s["text"] for s in segments)
            timeline_path.unlink(missing_ok=True)
            (meeting_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
            # Persisted (not just used transiently) so a later .srt export can use the real
            # per-segment timestamps instead of guessing even splits across the duration.
            (meeting_dir / "segments.json").write_text(
                json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            summary = summarize(transcript, self.config["ollama_model"], self.config["ollama_url"])
            (meeting_dir / "summary.md").write_text(summary, encoding="utf-8")

            if self.config.get("ai_titles", True) and len(transcript.split()) >= MIN_WORDS_FOR_SUMMARY:
                ai_title = generate_title(summary, self.config["ollama_model"], self.config["ollama_url"])
                if ai_title:
                    update_meta(meeting_dir, ai_title=ai_title)

            if len(transcript.split()) >= MIN_WORDS_FOR_SUMMARY:
                tone = generate_tone(summary, self.config["ollama_model"], self.config["ollama_url"])
                if tone:
                    update_meta(meeting_dir, tone=tone)

            # Only auto-generate tags if the user hasn't already set any manually - this
            # always runs right after recording, before the user has had a chance to open
            # the tags/notes dialog, so there is nothing to clobber in practice, but the
            # check is kept explicit so it stays safe if that ordering ever changes.
            if self.config.get("ai_tags", True) and len(transcript.split()) >= MIN_WORDS_FOR_SUMMARY:
                existing_tags = load_meta(meeting_dir).get("tags", [])
                if not existing_tags:
                    ai_tags = generate_tags(summary, self.config["ollama_model"], self.config["ollama_url"])
                    if ai_tags:
                        update_meta(meeting_dir, tags=ai_tags)

            if not self.config.get("keep_audio", False):
                wav_path.unlink(missing_ok=True)

            self._emit("processing_done", meeting_dir=meeting_dir, summary=summary, transcript=transcript)
        except Exception as exc:
            logger.exception("processing failed: %s", exc)
            self._emit("error", message=t("error_processing", exc=exc), meeting_dir=meeting_dir)
