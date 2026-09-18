"""פקודות קוליות להתחלה/עצירה של הקלטה - "מצב מאוזן" (armed) שנדלק ידנית לזמן מוגבל
(60 שניות כברירת מחדל) ואז כבה לבד. לא מאזין תמיד ברקע - נדלק רק כשמבקשים,
כדי לא להחזיק מיקרופון פתוח כל הזמן.

משתמש במודל התמלול הקיים (ivrit-ai/faster-whisper) על קטעים קצרים, ולא בספריית
זיהוי-מילת-הפעלה נפרדת: אין מודל offline טוב לעברית לזיהוי מילת הפעלה (Vosk לא
תומך בעברית), והחלופה המובילה (Porcupine) דורשת חשבון/מפתח גישה חיצוני - מנוגד
לעיקרון "בלי חשבונות" של Scriptly. המחיר: זיהוי כל 2-3 שניות ולא מיידי כמו
מילת-הפעלה ייעודית, אבל בלי תלות חדשה ובלי לפגוע בפרטיות."""
import tempfile
import threading
import time
import wave
from pathlib import Path

import pyaudiowpatch as pyaudio

from .logger import get_logger
from .transcribe import transcribe_segments

logger = get_logger(__name__)

POLL_SECONDS = 2.5
CLIP_SECONDS = 2.2

START_PHRASES = ["תתחיל הקלטה", "התחל הקלטה", "תתחילי הקלטה", "start recording"]
STOP_PHRASES = ["תפסיק הקלטה", "עצור הקלטה", "תפסיקי הקלטה", "stop recording"]


class VoiceCommandListener:
    """on_trigger(mode) נקרא כשזוהתה פקודה תואמת. get_config() מחזיר את config הנוכחי.
    on_disarmed() נקרא כשההאזנה מסתיימת (זוהתה פקודה, timeout, או disarm ידני)."""

    def __init__(self, on_trigger, get_config):
        self._on_trigger = on_trigger
        self._get_config = get_config
        self._armed = False
        self._stop_event = threading.Event()

    @property
    def is_armed(self) -> bool:
        return self._armed

    def arm(self, mode: str, duration_seconds: int = 60, on_disarmed=None) -> bool:
        if self._armed:
            return False
        self._armed = True
        self._stop_event.clear()
        threading.Thread(target=self._loop, args=(mode, duration_seconds, on_disarmed), daemon=True).start()
        return True

    def disarm(self) -> None:
        self._stop_event.set()

    def _loop(self, mode: str, duration_seconds: int, on_disarmed) -> None:
        deadline = time.time() + duration_seconds
        try:
            while time.time() < deadline and not self._stop_event.is_set():
                if self._check_once(mode):
                    self._on_trigger(mode)
                    break
                self._stop_event.wait(POLL_SECONDS)
        except Exception:
            logger.exception("voice command listener error")
        finally:
            self._armed = False
            if on_disarmed:
                on_disarmed()

    def _check_once(self, mode: str) -> bool:
        clip_path = self._record_clip()
        if clip_path is None:
            return False
        try:
            config = self._get_config()
            segments = transcribe_segments(
                clip_path, config["whisper_model"], config["whisper_device"],
                config["whisper_compute_type"], config["language"],
            )
            text = " ".join(s["text"] for s in segments).strip().lower()
        except Exception:
            logger.exception("voice command transcription failed")
            return False
        finally:
            clip_path.unlink(missing_ok=True)
        if not text:
            return False
        phrases = START_PHRASES if mode == "start" else STOP_PHRASES
        return any(p in text for p in phrases)

    def _record_clip(self):
        config = self._get_config()
        pa = pyaudio.PyAudio()
        stream = None
        try:
            mic_index = config.get("mic_device_index")
            info = pa.get_device_info_by_index(mic_index) if mic_index is not None else pa.get_default_input_device_info()
            channels = int(info["maxInputChannels"]) or 1
            rate = int(info["defaultSampleRate"])
            chunk = 1024
            stream = pa.open(
                format=pyaudio.paInt16, channels=channels, rate=rate,
                input=True, input_device_index=info["index"], frames_per_buffer=chunk,
            )
            frames = [stream.read(chunk, exception_on_overflow=False) for _ in range(int(rate / chunk * CLIP_SECONDS))]
        except Exception as exc:
            logger.warning("voice command mic sample failed: %s", exc)
            return None
        finally:
            if stream is not None:
                stream.stop_stream()
                stream.close()
            pa.terminate()

        tmp = Path(tempfile.gettempdir()) / f"scriptly_voice_{int(time.time() * 1000)}.wav"
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)  # paInt16 = 2 bytes/sample
            wf.setframerate(rate)
            wf.writeframes(b"".join(frames))
        return tmp
