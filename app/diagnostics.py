"""בדיקת תקינות המערכת - Ollama, GPU, מיקרופון, מקום בדיסק, תיקיית שמירה, וסנכרון ענן.

תוצאה של כל בדיקה: (level, title, detail) כאשר level אחד מ- "ok" / "warn" / "fail".
"""
import shutil
import subprocess
from pathlib import Path

import requests

from . import audio_devices
from .i18n import t

CLOUD_SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "icloud")


def check_ollama(ollama_url: str, model: str):
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=3)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        if any(model == n or n.startswith(model.split(":")[0]) for n in names):
            return "ok", t("diag_ollama_title"), t("diag_ollama_ok", model=model)
        return "warn", t("diag_ollama_title"), t("diag_ollama_missing_model", model=model)
    except Exception:
        return "fail", t("diag_ollama_title"), t("diag_ollama_unreachable")


def check_gpu():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            gpu_line = result.stdout.strip().splitlines()[0]
            return "ok", t("diag_gpu_title"), gpu_line
        return "warn", t("diag_gpu_title"), t("diag_gpu_none")
    except Exception:
        return "warn", t("diag_gpu_title"), t("diag_gpu_none")


def check_microphone(mic_device_index):
    try:
        devices = audio_devices.list_input_devices()
    except Exception:
        devices = []
    if not devices:
        return "fail", t("diag_mic_title"), t("diag_mic_none")
    if mic_device_index is not None and mic_device_index not in [i for i, _ in devices]:
        return "warn", t("diag_mic_title"), t("diag_mic_invalid_selection")
    name = next((n for i, n in devices if i == mic_device_index), devices[0][1])
    return "ok", t("diag_mic_title"), name


def check_disk_space(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(path).free / (1024**3)
        if free_gb < 1:
            return "fail", t("diag_disk_title"), t("diag_disk_low", gb=f"{free_gb:.1f}")
        if free_gb < 5:
            return "warn", t("diag_disk_title"), t("diag_disk_low", gb=f"{free_gb:.1f}")
        return "ok", t("diag_disk_title"), t("diag_disk_ok", gb=f"{free_gb:.0f}")
    except Exception as exc:
        return "fail", t("diag_disk_title"), str(exc)


def check_folder_writable(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".scriptly_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return "ok", t("diag_folder_title"), str(path)
    except Exception as exc:
        return "fail", t("diag_folder_title"), str(exc)


def check_cloud_sync(path: Path):
    path_str = str(path).lower()
    for marker in CLOUD_SYNC_MARKERS:
        if marker in path_str:
            return "warn", t("diag_cloud_title"), t("diag_cloud_warning")
    return "ok", t("diag_cloud_title"), t("diag_cloud_ok")


def run_all(config: dict):
    meetings_dir = Path(config["meetings_dir"])
    return [
        check_ollama(config["ollama_url"], config["ollama_model"]),
        check_gpu(),
        check_microphone(config.get("mic_device_index")),
        check_folder_writable(meetings_dir),
        check_disk_space(meetings_dir),
        check_cloud_sync(meetings_dir),
    ]
