# Scriptly PC

**Records, transcribes, and summarizes your meetings — 100% offline.**

## What it does

Scriptly PC is a Windows desktop app that records calls and meetings (your microphone and your computer's system audio at the same time), automatically transcribes them using a local Whisper engine tuned for Hebrew (`ivrit-ai/whisper-large-v3-turbo-ct2`), and produces a summary and action items using a local AI model through Ollama. It runs **completely offline** — no audio file, transcript, or summary ever leaves your computer, unless you explicitly connect a Google account to send a single task (opt-in, off by default). It's built for a single user who wants to document work meetings and calls without depending on a cloud service, an account, or a monthly subscription, with full Hebrew and English support (UI and RTL).

## Download & install

**Installer hosting is currently pending.** At roughly 2GB, the installer is over GitHub's 2GB-per-file limit for release assets, so it is not yet attached to a GitHub Release. Check the [GitHub repo](https://github.com/ofirshudari1-ship-it/scriptly-pc) and its [Releases page](https://github.com/ofirshudari1-ship-it/scriptly-pc/releases/latest) for the latest status — a proper download host is being worked on. The app's automatic update *check* already works via GitHub regardless; only the installer binary itself needs a permanent home.

Once available:

1. Download the Scriptly PC installer.
2. Run it — no administrator rights required by default.
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

Scriptly PC checks GitHub Releases for a newer version and shows a system-tray notification with a link when one is available — no account, no telemetry involved in the check itself. See the [Releases page](https://github.com/ofirshudari1-ship-it/scriptly-pc/releases) for version history.

## Privacy

Scriptly PC is fully local-first: audio, transcripts, and summaries never leave your machine. The only exception is a fully optional, off-by-default Google Tasks/Calendar integration, which only sends a task you explicitly choose to send.
