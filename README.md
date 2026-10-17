# Scriptly PC

**Records, transcribes, and summarizes your meetings — 100% offline.**

## What it does

**Claude AI (optional):** one pass returns the summary, meeting type (sales / support / team sync / planning / client / 1:1 / interview / brainstorm / negotiation / training), conclusions & decisions, tasks with owner and due date, results, practical tips, open questions and tags. Falls back to the local Ollama model automatically if the key is missing or the request fails.

Scriptly PC is a Windows desktop app that records calls and meetings (your microphone and your computer's system audio at the same time), automatically transcribes them using a local Whisper engine tuned for Hebrew (`ivrit-ai/whisper-large-v3-turbo-ct2`), and produces a summary and action items using a local AI model through Ollama. It runs **completely offline** — no audio file, transcript, or summary ever leaves your computer, unless you explicitly opt in to one of two optional features, both off by default: connecting a Google account to send a single task, or enabling **Claude AI** analysis (Settings → Transcription & Summary), which sends only the *text* transcript to Anthropic's API after an explicit consent prompt — audio and transcription always stay local. It's built for a single user who wants to document work meetings and calls without depending on a cloud service, an account, or a monthly subscription, with full Hebrew and English support (UI and RTL).

## Download & install

**[Download the latest Windows installer (Scriptly-PC-Setup-0.18.1.exe, ~210MB)](https://github.com/ofirshudari1-ship-it/scriptly-pc/releases/latest)**
from the Releases page. The default installer is **CPU-only** (it was ~2GB before
v0.18.0 - see [CHANGELOG.md](CHANGELOG.md) - because the old build bundled ~1.8GB
of CUDA/cuDNN libraries for every user, whether or not they had a compatible
NVIDIA GPU). The installer asks for administrator approval once (it installs
to Program Files).

A GPU-accelerated variant (faster transcription, ~2GB, requires an NVIDIA
GPU) can be built with `build\build.ps1 -IncludeGPU` — see `build/requirements-gpu.txt`.

1. Download the Scriptly PC installer.
2. Run it and approve the Windows administrator prompt (it installs to Program Files).
3. Follow the setup wizard: license, install location, language (English/Hebrew).
4. On first run, Scriptly PC downloads the Whisper and Ollama models (~7GB) once, over your own connection.
5. After that first-time download, Scriptly PC never needs the internet again.

**System requirements:** Windows 10/11, ~7GB free disk space for local AI models, a microphone.

## Key features

- Simultaneous microphone + system-audio recording (WASAPI loopback), with automatic speaker detection based on relative audio levels — no extra model needed.
- Fully local transcription (faster-whisper + ivrit-ai), with support for a custom terminology dictionary.
- Automatic summary and action-item extraction via a local Ollama model.
- AI-generated titles and topic tags for every recording.
- Conversation tone analysis (positive / neutral / tense).
- Statistics dashboard: talk-time ratio, 14-day trend, top tags.
- Export to Word / Markdown / plain text, including a multi-recording "digest" report and per-recording SRT subtitle export with real timestamps.
- Search and grouping of recordings (today / yesterday / this week / earlier), tags, and notes.
- A "hide recordings that look like background noise" filter — a local heuristic that flags recordings with unusually sparse transcripts relative to their length.
- A memory safety net: a recording accidentally left running for hours (sleeping PC, forgotten hotkey) auto-stops and saves once it hits a configurable size limit, instead of crashing the app.
- Optional Google Tasks/Calendar connection (OAuth, fully opt-in).
- Voice commands ("start/stop recording") via a user-initiated listening window, not always-on listening.
- A draggable floating recording button (overlay) and a global keyboard shortcut to start/stop recording from anywhere.
- Dark/Light/System theme, adjustable text size, full Hebrew RTL layout.
- Built-in system check for Ollama, GPU, microphone, and disk space.

## Automatic updates

Scriptly PC checks GitHub Releases shortly after launch and then every ~6 hours. By default it downloads a newer version, verifies it (size, executable header, sha256) and installs it when you are not recording or when you close the app; Windows asks for administrator approval once per update. This can be turned off in Settings ("Install updates automatically"). No account and no telemetry are involved. See the [Releases page](https://github.com/ofirshudari1-ship-it/scriptly-pc/releases) for version history.

## Privacy

Scriptly PC is fully local-first: audio, transcripts, and summaries never leave your machine. The only exception is a fully optional, off-by-default Google Tasks/Calendar integration, which only sends a task you explicitly choose to send.
