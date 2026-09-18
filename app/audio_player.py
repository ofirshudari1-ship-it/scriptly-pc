"""נגן WAV מינימלי דרך winsound (מובנה ב-Windows, בלי תלות נוספת) - כדי שאפשר יהיה להאזין
להקלטה מתוך הדשבורד עצמו, בלי לצאת לתיקייה ולפתוח נגן חיצוני. תומך רק בהשמעה/עצירה
(אין seek/pause אמיתיים - winsound לא תומך בזה), שזה מספיק בשביל "האזן להקלטה שלי"."""
from pathlib import Path

import winsound


class SimplePlayer:
    def __init__(self):
        self._playing_path = None

    @property
    def is_playing(self) -> bool:
        return self._playing_path is not None

    def play(self, wav_path: Path) -> None:
        winsound.PlaySound(str(wav_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        self._playing_path = wav_path

    def stop(self) -> None:
        winsound.PlaySound(None, winsound.SND_PURGE)
        self._playing_path = None
