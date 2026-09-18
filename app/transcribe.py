"""תמלול קובץ אודיו לעברית באמצעות faster-whisper עם מודל ivrit-ai (מקומי, ללא ענן)."""
import os
import sys
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)


def _register_cuda_dll_dirs():
    """מרשום את תיקיות ה-DLL של cuBLAS/cuDNN (מותקנות דרך pip) כדי ש-CTranslate2 ימצא אותן ב-Windows."""
    if sys.platform != "win32":
        return
    try:
        if getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))
        else:
            base = Path(sys.prefix) / "Lib" / "site-packages"
        candidates = [
            base / "nvidia" / "cublas" / "bin",
            base / "nvidia" / "cudnn" / "bin",
        ]
        for dll_dir in candidates:
            if dll_dir.is_dir():
                os.add_dll_directory(str(dll_dir))
                os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
            else:
                logger.warning("expected CUDA dll directory not found: %s", dll_dir)
    except Exception as exc:
        logger.warning("could not register CUDA dll directories: %s", exc)


_register_cuda_dll_dirs()

from faster_whisper import WhisperModel  # noqa: E402  (import after DLL dirs are registered)

_model_cache = {}


def _get_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    key = (model_name, device, compute_type)
    if key not in _model_cache:
        logger.info("loading whisper model %s on %s (%s)...", model_name, device, compute_type)
        try:
            _model_cache[key] = WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as exc:
            logger.warning("failed loading on %s (%s): %s - falling back to CPU/int8", device, compute_type, exc)
            _model_cache[key] = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _model_cache[key]


def transcribe_segments(
    wav_path: Path, model_name: str, device: str, compute_type: str, language: str = "he", hotwords: str = ""
) -> list:
    """מחזיר רשימת קטעים {start, end, text} (שניות יחסית לתחילת ההקלטה) - משמש לתיוג דוברים."""
    model = _get_model(model_name, device, compute_type)
    kwargs = dict(
        language=language,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
    )
    if hotwords and hotwords.strip():
        kwargs["hotwords"] = hotwords.strip()
    segments, info = model.transcribe(str(wav_path), **kwargs)
    result = [
        {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        for seg in segments
        if seg.text.strip()
    ]
    total_chars = sum(len(s["text"]) for s in result)
    logger.info("transcribed %s: %d chars, detected language=%s", wav_path.name, total_chars, info.language)
    return result


def transcribe(wav_path: Path, model_name: str, device: str, compute_type: str, language: str = "he", hotwords: str = "") -> str:
    segments = transcribe_segments(wav_path, model_name, device, compute_type, language, hotwords)
    return "\n".join(s["text"] for s in segments)
