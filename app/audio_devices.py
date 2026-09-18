"""עזרי בחירת/בדיקת מיקרופון - משמש גם את אשף ההיכרות הראשוני וגם את ה-recorder."""
import numpy as np
import pyaudiowpatch as pyaudio

from .logger import get_logger

logger = get_logger(__name__)


def list_input_devices():
    """מחזיר [(index, name), ...] של התקני קלט אמיתיים (לא כולל loopback)."""
    devices = []
    pa = pyaudio.PyAudio()
    try:
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0 and not info.get("isLoopbackDevice", False):
                devices.append((info["index"], info["name"]))
    finally:
        pa.terminate()
    return devices


def get_default_input_device_index():
    pa = pyaudio.PyAudio()
    try:
        return pa.get_default_input_device_info()["index"]
    except Exception:
        return None
    finally:
        pa.terminate()


def test_microphone(device_index, seconds: float = 2.0) -> float:
    """מקליט בקצרה מהתקן נתון ומחזיר את רמת השיא (0.0-1.0)."""
    pa = pyaudio.PyAudio()
    try:
        info = pa.get_device_info_by_index(device_index)
        channels = int(info["maxInputChannels"]) or 1
        rate = int(info["defaultSampleRate"])
        chunk = max(1, int(rate * 0.1))
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=chunk,
        )
        peak = 0.0
        n_chunks = max(1, int(seconds / 0.1))
        try:
            for _ in range(n_chunks):
                data = stream.read(chunk, exception_on_overflow=False)
                samples = np.frombuffer(data, dtype=np.float32)
                if len(samples):
                    peak = max(peak, float(np.abs(samples).max()))
        finally:
            stream.stop_stream()
            stream.close()
        return peak
    except Exception as exc:
        logger.warning("microphone test failed: %s", exc)
        return 0.0
    finally:
        pa.terminate()
