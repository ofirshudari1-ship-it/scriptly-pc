"""Heuristic conflict check for the global recording hotkey (STANDARDS.md 12.4).

Not an exhaustive list (there is no API to enumerate every hotkey every running
app has registered) - just the well-known Windows system shortcuts and the
shortcuts OBS Studio / Discord ship as commonly-used bindings, normalized so
"Ctrl+Alt+M", "ctrl+alt+m", and "CTRL + ALT + M" all compare equal (same
normalization style as the `keyboard` library itself uses for hotkey strings)."""

# combo (normalized, no spaces, lowercase, "+"-joined) -> human description shown in the warning
KNOWN_CONFLICTS = {
    "win+l": "Windows - Lock screen",
    "win+d": "Windows - Show desktop",
    "win+e": "Windows - File Explorer",
    "win+r": "Windows - Run dialog",
    "win+tab": "Windows - Task View",
    "win+g": "Windows - Xbox Game Bar",
    "win+alt+r": "Windows Game Bar - Record video",
    "win+alt+g": "Windows Game Bar - Record last 30 seconds",
    "win+shift+s": "Windows - Snip & Sketch (screenshot)",
    "win+p": "Windows - Project/display switch",
    "win+i": "Windows - Settings",
    "ctrl+alt+delete": "Windows - Security screen",
    "ctrl+alt+del": "Windows - Security screen",
    "ctrl+shift+esc": "Windows - Task Manager",
    "alt+tab": "Windows - Switch windows",
    "alt+f4": "Windows - Close window",
    "print screen": "Windows - Screenshot",
    "printscreen": "Windows - Screenshot",
    "ctrl+shift+m": "Discord - Mute/unmute microphone (common binding)",
    "ctrl+shift+d": "Discord - Deafen (common binding)",
    "ctrl+shift+r": "OBS Studio - Start/stop recording (common binding)",
    "ctrl+shift+s": "OBS Studio - Start/stop streaming (common binding)",
    "ctrl+shift+p": "OBS Studio - Start/stop replay buffer (common binding)",
}


def _normalize(hotkey: str) -> str:
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    return "+".join(parts)


def find_conflict(hotkey: str) -> str | None:
    """Returns a human-readable description of what commonly-used shortcut the
    given hotkey string collides with, or None if it looks clear. Never raises -
    an unparseable string just means "no known conflict", not an error."""
    if not hotkey:
        return None
    return KNOWN_CONFLICTS.get(_normalize(hotkey))
