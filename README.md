# Scriptly PC — מסמך אפיון

> מקליט. מתמלל. מסכם. לגמרי אופליין.

כלי Windows שרץ ברקע ומקליט כל שיחה שקורית במחשב — פגישה, שיחת מכירה,
שיחת טלפון בדפדפן, הקלטה אישית - ללא תלות באפליקציה (Zoom, Google Meet,
Skype, Teams, כל תוכנת VoIP אחרת) - מתמלל אותה לעברית ומפיק תקציר +
רשימת משימות. **הכל רץ מקומית על המחשב, ללא שליחת קול או טקסט לענן.**

לעדכוני גרסאות ראו [CHANGELOG.md](CHANGELOG.md).

---

## English

*This section covers what/who/install/usage/requirements/troubleshooting in
English, per the project's bilingual documentation standard. The deeper
sections below (competitive research, architecture rationale) stay Hebrew-only
- they're internal design reasoning, not user-facing instructions, so a full
word-for-word mirror would duplicate effort without adding anything an English
user actually needs. Everything an end user needs to install, run, and
troubleshoot Scriptly PC is here.*

### What it is

Scriptly PC is a Windows background app that records any conversation
happening on your computer - meetings, sales calls, browser-based calls
(Zoom, Google Meet, Teams, Skype, or any other VoIP app) - independent of
which app is doing the talking. It transcribes the recording, then produces
a summary and a task list. **Everything runs locally on your machine. No
audio or text is ever sent to the cloud**, except when you explicitly connect
an optional Google account and explicitly send one task - a feature that is
off by default.

### Who it's for

A single Windows user who wants a written record of their meetings/calls
without a cloud subscription, a monthly fee, or sending business
conversations to a third-party server.

### Installation

1. Run `Scriptly-PC-Setup-<version>.exe`.
2. Pick your language (English/Hebrew) on the very first screen - this also
   sets the app's own starting language (changeable anytime in Settings).
3. Choose an install folder (default: `C:\Program Files\Scriptly PC`) and any
   optional extras (desktop shortcut, autostart, taskbar quick-launch).
4. Click Install. The app launches automatically when done.
5. A short first-run setup screen appears (language/microphone/features/
   theme) - every field already has a sane default, so clicking "Skip for
   now" or pressing Esc is always safe.

### Usage

- **Start/stop recording:** the global hotkey (default `Ctrl+Alt+M`,
  changeable in Settings), the "Start Recording" button in the main window,
  or the floating record button on the desktop.
- Closing the main window (the X button) minimizes Scriptly PC to the system
  tray - it keeps running in the background so the hotkey still works. Left-
  click the tray icon to reopen the window; right-click it for a quick menu
  (including Quit, which is the only way to fully exit).
- After a recording stops, it's transcribed and summarized automatically
  (unless you turned that off in Settings, in which case click "Summarize
  Now" when ready).
- Each recording gets a transcript, a summary, key points, and a task list,
  plus optional tags/notes and audio playback (if "keep audio file" is on).
- Export a single recording (Word/Markdown/Text) or a multi-recording
  "Digest" (weekly/monthly/all-time overview) from the ☰ menu.

### Requirements

- Windows 10 (1809+) or Windows 11, 64-bit.
- A microphone (system audio - the other side of a call - is captured
  automatically alongside it, no extra setup needed).
- An NVIDIA GPU is recommended for fast transcription; the app falls back to
  CPU automatically (slower, but fully functional) if none is found.
- No account, no internet connection required for core functionality.
  Internet is only needed for the one-time optional Google Tasks/Calendar
  connection.

### Troubleshooting

- **Menu → System Check** runs an automatic diagnostic: Ollama connection,
  GPU detection, microphone, free disk space, and a warning if your
  recordings folder sits inside a cloud-sync folder (OneDrive/Dropbox).
- Logs: `data\scriptly.log` inside the install folder - useful context (not
  just a bare stack trace) if you need to report a problem.
- If the installer says Scriptly PC is already running, close it first (look
  for its icon near the clock, possibly in the hidden tray icons), then
  click Retry.
- The installer isn't digitally signed yet (documented, deliberate - see
  `build/sign.ps1`), so Windows SmartScreen may show a warning on first run.
  This doesn't indicate malware; it means the publisher hasn't yet built up
  SmartScreen reputation.

### Development

```bash
python -m venv venv
venv\Scripts\pip install -r build\requirements.txt -r build\requirements-dev.txt
venv\Scripts\python -m unittest discover tests
venv\Scripts\pythonw run.pyw
```

Full build (exe + installer, one command): `powershell -ExecutionPolicy Bypass -File build\build.ps1`

---

## 1. הבעיה

שיחות עבודה מסתיימות בלי סיכום כתוב ובלי רשימת משימות מסודרת - מידע הולך
לאיבוד ומעקב אחרי התחייבויות תלוי בזיכרון. זה קורה בכל שיחה: פגישת לקוח בזום,
שיחת מכירה בטלפון, בדיקת סטטוס פנימית - ברגע שהשיחה נגמרת, מה שנשאר זה מה
שמישהו הספיק לזכור לכתוב. הבטחות ("אני אשלח לך עד יום חמישי") נעלמות. מי שלא
היה בשיחה לא יודע מה סוכם. ומעקב אחרי "מי אמר מה" בין כמה שיחות עם אותו לקוח
הופך בלתי אפשרי בלי לחפש בזיכרון.

הפתרונות הקיימים (Otter, Fireflies, Fathom, Granola) פותרים את זה היטב - אבל
דורשים חשבון בענן, לרוב בתשלום חודשי, ושולחים את תוכן השיחות (כולל שיחות
עסקיות רגישות) לשרתים של צד שלישי.

## 2. למה Scriptly PC

Scriptly PC נבנה כתשובה ל"אני צריך את מה ש-Otter נותן, אבל בלי לשלוח כל שיחה
עסקית שלי לענן של מישהו אחר, ובלי מנוי חודשי." שלוש סיבות מרכזיות לבחור בו:

1. **אפס עלות שוטפת, אפס תלות ברשת** - אחרי ההתקנה החד-פעמית (שדורשת הורדת
   מודלים, כ-7GB), התוכנה עובדת גם ללא אינטרנט בכלל. אין מנוי, אין "קרדיטים"
   שנגמרים, אין הפתעות בחיוב.
2. **פרטיות מובנית, לא מובטחת** - זה לא "אנחנו מבטיחים לא לשמור את הקול שלך";
   זה שהקול שלך פיזית לא עוזב את המחשב, כי אין שום קריאת רשת בכל שרשרת
   העיבוד (ראו §10). למי שעובד עם מידע רגיש של לקוחות (פרטי אשראי, מידע
   רפואי, חוזים) - זה לא נוחות, זו דרישה.
3. **מותאם לעברית** - מודל התמלול (`ivrit-ai`) אומן ספציפית על עברית מדוברת,
   לא "גם תומך בעברית" כמו רוב הכלים הבינלאומיים.

**למי זה מתאים**: אנשי מכירות ושירות שרוצים תיעוד אוטומטי של שיחות לקוח בלי
לתייק ידנית; מנהלים שרוצים לראות מה סוכם בפגישה בלי להיות בה; כל מי שעובד
עם מידע עסקי רגיש ולא יכול/רוצה שהוא יעבור דרך שרת חיצוני.

## 3. מחקר תחרותי (Otter.ai / Fireflies / Fathom / Granola)

לפני ההרחבה האחרונה נבדק מה כלים מובילים בקטגוריית "AI meeting notetaker"
מציעים כיום, כדי לזהות פערים:

| ממצא | מקור | השלכה על Scriptly PC |
|---|---|---|
| Granola בנוי בדיוק על אותה גישה: אפליקציה מקומית שמקליטה מיקרופון+אודיו מערכת בלי "בוט" שמצטרף לשיחה | [Feisworld: Best AI Notetakers 2026](https://www.feisworld.com/blog/best-ai-notetakers-2026) | מאמת שהארכיטקטורה שנבחרה (WASAPI loopback + מיקרופון, ללא אינטגרציה לזום) נכונה ותחרותית, לא רק "פתרון עוקף" |
| זיהוי דוברים (speaker identification) הפך לפיצ'ר סטנדרטי אצל כל הכלים המובילים | [itsconvo: Otter vs Fireflies vs Fathom](https://www.itsconvo.com/blog/otter-vs-fireflies-vs-fathom) | הוספנו תיוג "אתה / הצד השני" (ראו §5) |
| ארכיון תמלולים חיפושי הוא הבדל מרכזי בין הכלים (Otter מתמקד בזה) | [zackproser: Best AI Meeting Notes 2026](https://zackproser.com/blog/best-ai-meeting-notes-2026) | הוספנו חיפוש טקסט מלא (לא רק כותרות) על פני כל ההקלטות |
| כלים בענן דוחפים משימות ל-CRM (Salesforce/HubSpot) | [zackproser](https://zackproser.com/blog/best-ai-meeting-notes-tools-2026) | לא רלוונטי לכלי מקומי אישי - הוחלף בייצוא ל-Word (§5) שאפשר לצרף לכל מייל/CRM ידנית |
| הפער האמיתי אצל רוב הכלים: משימות "נתפסות" אבל לא זזות לשום מקום, והסיכומים נשארים באפליקציה נפרדת שאף אחד לא חוזר אליה | [Medium: Best AI Meeting Note-Takers 2026 (90-day test)](https://medium.com/@justtalkingtech/best-ai-meeting-note-takers-in-2026-i-tested-14-over-90-days-heres-the-honest-ranking-a7ea13fb8b47) | כבר נפתר ב-Scriptly PC (My Tasks מרוכז + חיפוש + ייצוא) לפני שהמחקר הזה בכלל בוצע |
| Fireflies.ai הכי חזק בדשבורד אנליטי (יחסי דיבור וכו') מבין הכלים שנבדקו | [tooldirectory.ai: AI notetakers 2026](https://tooldirectory.ai/blog/ai-notetakers-2026-otter-fireflies-granola-fathom-read) | הוספנו דשבורד תובנות (§5): יחס דיבור, מגמת שימוש, תגיות מובילות |

מקור טכני נוסף: אימות ש-faster-whisper תומך רשמית בפרמטר `hotwords` לחיזוק
זיהוי שמות/מונחים ([DeepWiki: faster-whisper Advanced Features](https://deepwiki.com/SYSTRAN/faster-whisper/8.2-advanced-features),
[Sotto: Improve Whisper Accuracy with Prompts](https://sotto.to/blog/improve-whisper-accuracy-prompts)) - מומש כ"מילון מונחים מותאם" בהגדרות.

## 4. הפתרון וההחלטות המרכזיות

| החלטה | מה נבחר | למה |
|---|---|---|
| תמלול (ASR) | מודל מקומי `ivrit-ai/whisper-large-v3-turbo-ct2` דרך faster-whisper | מותאם לעברית, רץ על GPU מקומי, חינמי, לא שולח קול לענן |
| סיכום + משימות | LLM מקומי `aya-expanse:8b` דרך Ollama | מודל רב-לשוני עם תמיכה מוכחת בעברית, רץ מקומית ב-VRAM של 8GB, חינמי |
| לכידת אודיו | WASAPI loopback (אודיו יוצא של Windows) + מיקרופון, נשמרים גם בנפרד וגם ממוזגים | לוכד כל שיחה בכל אפליקציה; שמירת הערוצים בנפרד גם מאפשרת תיוג דוברים בלי מודל נוסף |
| זיהוי דוברים | היוריסטיקה מבוססת עוצמה (RMS) - איזה ערוץ (מיקרופון/מערכת) דומיננטי בכל 100ms | חינמי, מקומי, בלי מודל diarization נוסף; מספיק לשיחת שני צדדים (את/ה + הצד השני) |
| הפעלה | קיצור מקלדת גלובלי (ברירת מחדל `Ctrl+Alt+M`) + חלון צף + דשבורד | לא דורש מעבר אפליקציה כדי להתחיל/לעצור הקלטה |
| ממשק | דשבורד מלא (CustomTkinter), מצב כהה/בהיר, ברירת מחדל אנגלית עם מעבר לעברית | לא רק אייקון מגש נסתר - רואים הקלטות, סיכומים ומשימות בתוך התוכנה |
| מיתוג | **Scriptly PC** - לוגו: גל קול + וי (משימות בוצעו) | ראו `assets/icon_idle.png`; שם כללי, לא קשור למילה "פגישה" |
| פקודות קוליות | חלון "מזוין" (60 שניות) שבודק קטעי מיקרופון מול מנוע התמלול הקיים (ivrit-ai) | Porcupine דורש חשבון/מפתח חיצוני, Vosk לא תומך בעברית - שתי החלופות המובילות לא התאימו |

### חלופות שנשקלו ולא נבחרו

- **תמלול/סיכום בענן** (OpenAI/Azure/Claude) - דיוק גבוה יותר אך כרוך בעלות מתמשכת ובשליחת תוכן שיחות (פוטנציאלית רגיש) לצד שלישי.
- **Diarization מלא** (מודל ייעודי כמו pyannote) - דיוק גבוה יותר ותמיכה ביותר משני דוברים, אך דורש הורדת מודל נוסף וטוקן HuggingFace; ההיוריסטיקה מבוססת-עוצמה שנבחרה מספיקה לרוב המקרים (שיחת שני צדדים) בלי תלות נוספת.
- **זיהוי אוטומטי של תחילת שיחה** - נשקל (ניטור רקע של עוצמת אודיו מערכת), נדחה בשלב זה בגלל סיכון False positive גבוה (סרטון יוטיוב/מוזיקה גם מייצרים אודיו מערכת) - נשאר לשלב הבא.

## 5. ארכיטקטורה ופיצ'רים

```
                 ┌──────────────────────┐
 מיקרופון  ───▶ │                      │──▶ speaker_timeline.json (עוצמה כל 100ms)
                 │   audio_capture.py    │──▶ recording.wav (16kHz mono, ממוזג)
 רמקולים   ───▶ │  (WASAPI loopback)    │
 (כל אפליקציה)   └──────────────────────┘
                             │
                             ▼
                 ┌──────────────────────┐
                 │    transcribe.py      │   faster-whisper + ivrit-ai + hotwords
                 │  (GPU, מקומי)         │──▶ קטעים עם timestamps
                 └──────────────────────┘
                             │  (controller.py ממזג עם speaker_timeline)
                             ▼
                 ┌──────────────────────┐
                 │    summarize.py       │   Ollama + aya-expanse:8b
                 │  (מקומי)              │──▶ summary.md + transcript.txt (מתויג "אתה/הצד השני")
                 └──────────────────────┘
```

### מודולי ליבה

- **`app/main.py`** — נקודת הכניסה: מרכיב דשבורד + מגש + חלון צף + אשף היכרות.
- **`app/controller.py`** — מקור אמת יחיד למצב ההקלטה; ממזג תמלול עם ציר הדוברים.
- **`app/dashboard.py`** — חלון ראשי: חיפוש, קבוצות תאריך, סיכום/תמלול/תגיות, ייצוא, מחיקה, סטטיסטיקה, בדיקת תקינות.
- **`app/overlay.py`** — חלון צף (HUD) בזמן הקלטה.
- **`app/tray.py`** — אייקון מגש המערכת.
- **`app/onboarding.py`** — אשף הפעלה ראשונה (בחירת/בדיקת מיקרופון).
- **`app/audio_capture.py`** — הקלטה + מיזוג + חישוב ציר דוברים.
- **`app/audio_devices.py`** — רשימת/בדיקת מיקרופונים.
- **`app/transcribe.py`** — תמלול עם timestamps + hotwords.
- **`app/summarize.py`** — סיכום + הגנה מפני המצאת תוכן.
- **`app/meetings.py`** — סריקת הקלטות + מטא-דאטה (תגיות/הערות/משך).
- **`app/meta.py`** — קריאה/כתיבה של `meta.json` לכל הקלטה.
- **`app/export.py`** — ייצוא הקלטה ל-Word (.docx).
- **`app/stats.py`** — סטטיסטיקה (סה"כ הקלטות, זמן, ממוצע, יום עמוס).
- **`app/diagnostics.py`** — בדיקת תקינות (Ollama, GPU, מיקרופון, דיסק, פרטיות ענן).
- **`app/autostart.py`** / **`app/single_instance.py`** / **`app/i18n.py`** / **`app/config.py`** — תשתית.

### פיצ'רים עיקריים

| פיצ'ר | איפה |
|---|---|
| הקלטה + תמלול + סיכום אוטומטי | כפתור ראשי / קיצור מקלדת / חלון צף |
| **תיוג דוברים** ("אתה" / "הצד השני") | אוטומטי בתמלול, ניתן לכיבוי בהגדרות |
| **מילון מונחים מותאם** (hotwords) | הגדרות → Transcription & Summary |
| **חיפוש טקסט מלא** (כותרת + תקציר + תמלול + הערות + תגיות) | תיבת חיפוש מעל רשימת ההקלטות |
| **קיבוץ לפי תאריך** (היום/אתמול/השבוע/קודם) | רשימת הקלטות |
| **תגיות + הערות אישיות** לכל הקלטה | כפתור 🏷 |
| **"המשימות שלי"** - כל המשימות מכל ההקלטות במסך אחד, עם סימון בוצע | תפריט ☰ → My Tasks |
| **תמיכה בפגישות ארוכות** (פיצול+מיזוג אוטומטי לתמלולים ארוכים) | אוטומטי, ללא הגדרה |
| **כותרות אוטומטיות בבינה מלאכותית** לכל הקלטה, על בסיס הסיכום | אוטומטי, ניתן לכיבוי בהגדרות |
| **גודל טקסט מתכוונן** (נגישות) | הגדרות → Interface → Text size |
| **דשבורד תובנות** - יחס דיבור, מגמת שימוש ל-14 יום, תגיות מובילות, פילוח טון שיחות | תפריט ☰ → Statistics |
| **כפתור הקלטה צף קבוע** - התחלת הקלטה בלחיצה אחת, בלי דשבורד ובלי קיצור מקלדת | ניתן לכיבוי בהגדרות |
| **זיהוי טון שיחה** (חיובי/ניטרלי/מתוח) לכל הקלטה | אוטומטי, מוצג ברשימה ובדשבורד התובנות |
| **חיבור אופציונלי ל-Google Tasks / Calendar** - שליחת משימה בודדת בלחיצת כפתור | כבוי כברירת מחדל, הגדרות → Integrations (ראו §10) |
| **ייצוא דוח מרוכז (Digest)** - תמונת מצב + משימות פתוחות + תקציר לכל הקלטה, על פני טווח שלם | תפריט ☰ → Export Digest… |
| **האזנה להקלטה מתוך התוכנה** (אם "שמור קול" דלוק) | כפתור ▶ בתצוגת ההקלטה |
| **התחלה/עצירה בפקודה קולית** ("תתחיל/תפסיק הקלטה") | כבוי כברירת מחדל, כפתור 🎤 בסרגל הצף |
| **ייצוא ל-Word** | כפתור ⬇ Export |
| **מחיקה** (עם אישור) | כפתור 🗑 |
| **העתקה ללוח** | כפתור 📋 |
| **סיכום אוטומטי הפיך** (אפשר לכבות ולסכם ידנית) | הגדרות + כפתור "Summarize Now" |
| **סטטיסטיקה** | תפריט ☰ → Statistics |
| **בדיקת תקינות מערכת** (AI/GPU/מיקרופון/דיסק/פרטיות) | תפריט ☰ → System Check |
| מצב כהה/בהיר/מערכת | הגדרות → Interface |
| עברית/אנגלית לממשק | הגדרות → Interface |
| הפעלה אוטומטית עם Windows | הגדרות |

## 6. שימוש

1. האפליקציה נפתחת בדשבורד + אייקון במגש המערכת.
2. **הקלטה**: `Ctrl+Alt+M`, כפתור בדשבורד, או מהתפריט - בכל רגע, בכל אפליקציה.
3. אם "סיכום אוטומטי" דלוק (ברירת מחדל) - התמלול והסיכום מופקים אוטומטית. אחרת ההקלטה ממתינה ל-"Summarize Now".
4. **הגדרות** (⚙): קיצור מקלדת, תיקיית שמירה, מיקרופון, שמירת קול, סיכום אוטומטי, מילון מונחים, תיוג דוברים, כותרות AI, מודל סיכום, מנוע תמלול, מצב תצוגה, גודל טקסט, שפה, הפעלה אוטומטית, חיבור Google (אופציונלי).

### איפה הכל נשמר

כל הנתונים של Scriptly PC חיים בתוך תיקיית האפליקציה עצמה, בשתי תיקיות ברורות -
אין מסד נתונים נסתר, אין רישום ל-Windows Registry (מלבד הפעלה אוטומטית,
אם הופעלה), ואין שום דבר שנשמר "בענן":

```
Scriptly PC\
 ├─ Meetings\                     ← כל ההקלטות, תיקייה נפרדת לכל הקלטה
 │   └─ <תאריך>_<שעה>\
 │       ├─ transcript.txt        תמלול מלא, מתויג "אתה:" / "הצד השני:"
 │       ├─ summary.md            תקציר + נקודות מרכזיות + משימות
 │       ├─ meta.json             תגיות, הערות, כותרת AI, טון, משימות שסומנו כבוצעו
 │       └─ recording.wav         קובץ קול - רק אם "שמור הקלטה" דלוק בהגדרות
 └─ data\                         ← הגדרות ולוג התוכנה
     ├─ config.json                כל ההגדרות (§4-5), במקום אחד וקריא
     ├─ scriptly.log                לוג פעילות (להתחלת אבחון תקלות)
     └─ google_token.json           רק אם חיברתם חשבון Google - טוקן ההתחברות בלבד
```

אפשר להעביר את כל תיקיית `Scriptly PC` למחשב אחר או לכונן אחר והיא תמשיך לעבוד
בדיוק כמו שהיא - שום דבר לא "נעול" למיקום המקורי. `Meetings\` היא בעצם
התשובה ל"איפה כל הדאטה שלי" - כל מה שהתוכנה יודעת על ההקלטות שלכם נמצא שם,
בקבצי טקסט/JSON רגילים שאפשר לקרוא גם בלי Scriptly PC בכלל.

## 7. דרישות מערכת

- Windows 10/11, כרטיס מסך NVIDIA מומלץ (נבדק על RTX 4060, 8GB VRAM). בלי GPU - נופל אוטומטית ל-CPU (איטי יותר).
- [Ollama](https://ollama.com) מותקן ורץ, עם המודל `aya-expanse:8b`.
- כ-7GB פנויים לדיסק עבור המודלים.

## 8. הרצה בסביבת פיתוח

```bash
cd "Scriptly PC"
venv\Scripts\pythonw.exe run.pyw
```

או קיצור הדרך "Scriptly PC" מתפריט ההתחלה של Windows.

## 9. מגבלות ידועות ותוכנית המשך

- **זיהוי אוטומטי של תחילת שיחה** - נחקר, נדחה (ראו §4) - כרגע הפעלה ידנית בלבד.
- **פקודות קוליות** (§5) - הזיהוי בודק קטע קול כל כ-2.5 שניות ולא מיידי כמו מילת-הפעלה ייעודית (Alexa/Siri); דורש לומר את המשפט המלא בבירור. נבחר בכוונה על פני Porcupine (דורש חשבון חיצוני) ו-Vosk (לא תומך בעברית) - ראו הסבר ב-CHANGELOG v0.10.0.
- **תמלול בזמן אמת (כתוביות חיות)** - כרגע batch אחרי סיום ההקלטה, לא streaming.
- **תיוג דוברים מוגבל לשניים** ("אתה" / "הצד השני") - שיחות עם יותר מדובר אחד בכל צד (למשל שיחה משולשת) לא יתויגו נכון בלי diarization אמיתי.
- **`keyboard`** (קיצור מקלדת גלובלי) עלולה להיתפס כחשודה על ידי אנטי-וירוס בגלל hook ברמה נמוכה - תופעה ידועה, לא malware.

## 10. פרטיות ואבטחה

- שום קובץ קול, תמלול או סיכום לא עוזב את המחשב - כל העיבוד מקומי (ivrit-ai, aya-expanse).
- בדיקת התקינות (☰ → System Check) מתריעה אם תיקיית ההקלטות נמצאת בתוך תיקיית סנכרון ענן (OneDrive/Dropbox) - שם הקבצים עצמם עלולים להיות מועלים לענן גם אם התמלול עצמו מקומי.
- אין שום מפתח API, סיסמה או טוקן מאוחסן כברירת מחדל - כל הרכיבים (Whisper, Ollama) רצים ללא אימות מול שירות חיצוני.
- **היוצא מן הכלל היחיד**: חיבור ה-Google (§5) - כבוי כברירת מחדל, ופעיל רק אם המשתמש בעצמו יוצר Client ID/Secret ולוחץ "Connect". גם אז, כל לחיצה על "שלח ל-Google" שולחת אך ורק את הטקסט של המשימה הבודדת שנבחרה - לא את התמלול, לא את הסיכום, ולא שום הקלטה אחרת.
