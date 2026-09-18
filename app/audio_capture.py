"""הקלטת מיקרופון + אודיו יוצא של המערכת (WASAPI loopback) במקביל, ומיזוגם.

עובד ברמת מערכת ההפעלה - לא תלוי באפליקציה שמפעילה את השיחה
(Zoom / Google Meet בדפדפן / Skype / Teams וכו'), מכיוון שהוא קולט
את פלט הסאונד הכללי של Windows יחד עם המיקרופון.
"""
import json
import threading
import wave
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio

from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

TARGET_RATE = 16000
CHUNK_SECONDS = 0.1
TARGET_CHUNK_LEN = int(TARGET_RATE * CHUNK_SECONDS)


def _downmix_and_resample(raw_bytes: bytes, channels: int, orig_rate: int) -> np.ndarray:
    samples = np.frombuffer(raw_bytes, dtype=np.float32)
    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    if len(samples) == 0:
        return np.zeros(TARGET_CHUNK_LEN, dtype=np.float32)
    if orig_rate != TARGET_RATE:
        target_len = max(1, int(round(len(samples) * TARGET_RATE / orig_rate)))
        idx = np.linspace(0, len(samples) - 1, target_len)
        samples = np.interp(idx, np.arange(len(samples)), samples).astype(np.float32)
    if len(samples) != TARGET_CHUNK_LEN:
        idx = np.linspace(0, len(samples) - 1, TARGET_CHUNK_LEN)
        samples = np.interp(idx, np.arange(len(samples)), samples).astype(np.float32)
    return samples


class MeetingRecorder:
    """מקליט מיקרופון + אודיו מערכת במקביל וממזג לקובץ WAV יחיד (16kHz מונו)."""

    def __init__(self):
        self._pa = None
        self._mic_chunks = []
        self._sys_chunks = []
        self._stop_event = threading.Event()
        self._threads = []
        self._recording = False
        self._keepalive_stream = None
        self._keepalive_thread = None
        self._max_bytes = None
        self._on_size_limit = None
        # Set when a recording was auto-stopped because it hit `max_bytes` (see
        # start()) rather than because the user pressed stop - lets the caller
        # (controller.py) tell the two situations apart and warn the user instead
        # of silently truncating a long recording with no explanation.
        self.size_limit_hit = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _pick_devices(self, mic_device_index=None):
        pa = self._pa
        loopback = None
        try:
            loopback = pa.get_default_wasapi_loopback()
        except Exception:
            try:
                wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
                for dev in pa.get_loopback_device_info_generator():
                    if default_speakers["name"] in dev["name"]:
                        loopback = dev
                        break
            except Exception as exc:
                logger.warning("could not locate system-audio loopback device: %s", exc)

        mic = None
        try:
            if mic_device_index is not None:
                mic = pa.get_device_info_by_index(mic_device_index)
            else:
                mic = pa.get_default_input_device_info()
        except Exception as exc:
            logger.warning("could not locate microphone (index=%s): %s", mic_device_index, exc)
            try:
                mic = pa.get_default_input_device_info()
            except Exception:
                mic = None

        return mic, loopback

    def _start_keepalive(self, loopback_info):
        """מנגן שקט להתקן הפלט הרלוונטי כדי שהמנוע האודיו של Windows יישאר ער -
        בלי זה, כשלא מתנגן שום קול, קריאת ה-loopback עלולה להיתקע ללא הגבלת זמן."""
        try:
            pa = self._pa
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            out_info = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            channels = int(out_info["maxOutputChannels"]) or 2
            rate = int(out_info["defaultSampleRate"])
            chunk = max(1, int(rate * CHUNK_SECONDS))

            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=rate,
                output=True,
                output_device_index=out_info["index"],
            )
            silence = np.zeros(chunk * channels, dtype=np.float32).tobytes()

            def run():
                while not self._stop_event.is_set():
                    try:
                        stream.write(silence)
                    except OSError as exc:
                        logger.warning("keepalive write error: %s", exc)
                        break
                stream.stop_stream()
                stream.close()

            self._keepalive_stream = stream
            self._keepalive_thread = threading.Thread(target=run, daemon=True)
            self._keepalive_thread.start()
            logger.info("started silent keep-alive output on: %s", out_info["name"])
        except Exception as exc:
            logger.warning("could not start keep-alive output stream (loopback may stall if nothing is playing): %s", exc)
            self._keepalive_thread = None

    def start(self, mic_device_index=None, max_bytes=None, on_size_limit=None):
        """`max_bytes` (optional) is a soft cap on the in-memory recording buffer - both
        mic and system-audio chunks are kept fully in RAM until stop() mixes and writes
        them (see the class docstring), so a recording accidentally left running for
        many hours (laptop asleep with the meeting app still open, a forgotten hotkey,
        etc.) grows that buffer without bound and can OOM-crash the whole app, losing
        the entire recording. When the estimated buffer size crosses `max_bytes`, the
        capture threads stop themselves and `on_size_limit` (if given) is invoked once,
        from a fresh daemon thread so it can safely call back into stop() without
        deadlocking on this thread's own join(). None (the default) means no cap,
        preserving old behavior for any caller that doesn't pass one."""
        if self._recording:
            return
        self._pa = pyaudio.PyAudio()
        self._mic_chunks = []
        self._sys_chunks = []
        self._stop_event.clear()
        self._max_bytes = max_bytes
        self._on_size_limit = on_size_limit
        self.size_limit_hit = False

        mic_info, loopback_info = self._pick_devices(mic_device_index)
        if mic_info is None and loopback_info is None:
            self._pa.terminate()
            raise RuntimeError(t("error_no_audio_devices"))

        def make_reader(info, bucket, label):
            channels = int(info["maxInputChannels"]) or 1
            rate = int(info["defaultSampleRate"])
            chunk = max(1, int(rate * CHUNK_SECONDS))

            stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=info["index"],
                frames_per_buffer=chunk,
            )

            def run():
                logger.info("started capture: %s (rate=%s, ch=%s)", label, rate, channels)
                while not self._stop_event.is_set():
                    try:
                        data = stream.read(chunk, exception_on_overflow=False)
                    except OSError as exc:
                        logger.warning("%s read error: %s", label, exc)
                        break
                    bucket.append(_downmix_and_resample(data, channels, rate))
                    if self._max_bytes is not None and not self._stop_event.is_set():
                        # Approximate, not exact - each buffered chunk is TARGET_CHUNK_LEN
                        # float32 samples regardless of source rate/channels (see
                        # _downmix_and_resample), so this is cheap (no need to actually sum
                        # array byte sizes) and always a slight overestimate wrt in-flight
                        # chunks not yet appended in the other thread, both of which are fine
                        # for a soft safety cap rather than a hard accounting requirement.
                        approx_bytes = (len(self._mic_chunks) + len(self._sys_chunks)) * TARGET_CHUNK_LEN * 4
                        if approx_bytes >= self._max_bytes and not self._stop_event.is_set():
                            logger.warning(
                                "recording reached configured size limit (~%.1f GB) - stopping automatically",
                                self._max_bytes / (1024 ** 3),
                            )
                            self.size_limit_hit = True
                            self._stop_event.set()
                            if self._on_size_limit is not None:
                                threading.Thread(target=self._on_size_limit, daemon=True).start()
                stream.stop_stream()
                stream.close()
                logger.info("stopped capture: %s", label)

            return threading.Thread(target=run, daemon=True)

        self._threads = []
        if mic_info is not None:
            self._threads.append(make_reader(mic_info, self._mic_chunks, "microphone"))
        else:
            logger.warning("no microphone found - recording system audio only")
        if loopback_info is not None:
            self._start_keepalive(loopback_info)
            self._threads.append(make_reader(loopback_info, self._sys_chunks, "system-audio"))
        else:
            logger.warning("no system-audio loopback found - recording microphone only")

        for th in self._threads:
            th.start()

        self._recording = True

    def stop(self, output_wav_path: Path) -> Path:
        if not self._recording:
            raise RuntimeError(t("error_no_active_recording"))
        self._stop_event.set()
        for th in self._threads:
            th.join(timeout=5)
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=5)
            self._keepalive_thread = None
        self._pa.terminate()
        self._recording = False

        n = max(len(self._mic_chunks), len(self._sys_chunks))
        mixed = []
        for i in range(n):
            mic_c = self._mic_chunks[i] if i < len(self._mic_chunks) else np.zeros(TARGET_CHUNK_LEN, dtype=np.float32)
            sys_c = self._sys_chunks[i] if i < len(self._sys_chunks) else np.zeros(TARGET_CHUNK_LEN, dtype=np.float32)
            mixed.append(np.clip(mic_c + sys_c, -1.0, 1.0))

        full = np.concatenate(mixed) if mixed else np.zeros(0, dtype=np.float32)

        output_wav_path.parent.mkdir(parents=True, exist_ok=True)
        pcm16 = (full * 32767.0).astype(np.int16)
        with wave.open(str(output_wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_RATE)
            wf.writeframes(pcm16.tobytes())

        logger.info("saved mixed recording to %s (%.1fs)", output_wav_path, len(full) / TARGET_RATE)
        self._save_speaker_timeline(output_wav_path.parent / "speaker_timeline.json")
        return output_wav_path

    def _save_speaker_timeline(self, out_path: Path):
        """שומר, לכל 100ms, איזה ערוץ (מיקרופון/מערכת) היה דומיננטי - משמש לתיוג 'אתה/הצד השני'
        בתמלול. עובד רק כשיש גם מיקרופון וגם אודיו מערכת; אחרת לא נכתב קובץ."""
        if not self._mic_chunks or not self._sys_chunks:
            return
        n = min(len(self._mic_chunks), len(self._sys_chunks))
        labels = []
        for i in range(n):
            mic_energy = float(np.sqrt(np.mean(self._mic_chunks[i] ** 2)))
            sys_energy = float(np.sqrt(np.mean(self._sys_chunks[i] ** 2)))
            if mic_energy < 0.01 and sys_energy < 0.01:
                labels.append("silence")
            elif mic_energy > sys_energy * 1.2:
                labels.append("you")
            elif sys_energy > mic_energy * 1.2:
                labels.append("other")
            else:
                labels.append("both")
        try:
            out_path.write_text(
                json.dumps({"chunk_seconds": CHUNK_SECONDS, "labels": labels}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("could not write speaker timeline: %s", exc)
