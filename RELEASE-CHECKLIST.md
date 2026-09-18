# RELEASE-CHECKLIST.md

צ'קליסט לפני כל שחרור גרסה של Scriptly PC. מבוסס על ה-Definition of Done
המשותף ב-`_AUDIT/STANDARDS.md` §10, מותאם לכלי הזה.

## לפני הבנייה

- [ ] `version.json` עודכן לגרסה החדשה
- [ ] `CHANGELOG.md` מכיל ערך חדש (Added/Changed/Fixed/Removed), עברית+אנגלית
- [ ] `locales/en.json` ו-`locales/he.json` — אותם מפתחות בשני הקבצים
      (`python -m unittest tests.test_smoke` בודק את זה אוטומטית)
- [ ] `build/requirements.txt` נעול לגרסאות מדויקות, נבדק `pip install --dry-run` נקי
- [ ] `python -m unittest discover tests` — כל הבדיקות עוברות

## בנייה

- [ ] `build\build.ps1` רץ מקצה לקצה במכונה נקייה (venv חדש)
- [ ] קובץ ההתקנה היחיד שנוצר: `Scriptly-PC-Setup-<version>.exe` **בשורש הפרויקט**
- [ ] אין קבצי `dist/`, `build/pyinstaller_work/` שנשארו אחרי הבנייה
- [ ] אין יותר מקובץ התקנה אחד בשורש (בדוק שאין גרסה קודמת ששכחה להימחק)

## בדיקות ידניות על ההתקנה

- [ ] התקנה נקייה למחשב וירטואלי/משתמש נקי — מסך שפה מוצג ראשון (עברית+אנגלית)
- [ ] התקנה כשהאפליקציה כבר פתוחה → מוצגת הודעה ברורה (לא קריסה/נעילת קובץ)
- [ ] התקנה מעל גרסה קודמת = "עדכון" — רשומה **אחת** ב"הוספה והסרה של תוכניות" (לא שתיים)
- [ ] בלי הרשאות אדמין → נופל חזרה ל-`{localappdata}\Programs\Scriptly PC` בלי כישלון
- [ ] הפעלה ראשונה: splash (800-1500ms) → אשף onboarding (כפתור דלג עובד, Esc עובד)
- [ ] מעבר שפה עברית↔אנגלית מלא כולל RTL — גם באפליקציה וגם במתקין
- [ ] Dark/Light/System theme עובדים
- [ ] הסרת התקנה: שואלת על מחיקת דאטה (ברירת מחדל=לא), מנקה קבצים+קיצורים+רישום נקי

## אחרי השחרור

- [ ] גרסה זהה מוצגת בכל המקומות: כותרת חלון, מסך About, שם קובץ ההתקנה, `version.json`
- [ ] אין secrets/API keys בקוד שהועלה
- [ ] תיקיית הפרויקט נקייה: רק `Scriptly-PC-Setup-<version>.exe` / `CHANGELOG.md` /
      `SPEC.md` / `README.md` / `USER-GUIDE.md` / `RELEASE-CHECKLIST.md` /
      `version.json` / `site/` / `data/` / `assets/` / `locales/` / `tests/` / `app/` /
      `build/` (עם כל קבצי ה-build בפנים) גלויים בשורש

## חתימה דיגיטלית (ידני, לא אוטומטי)

- [ ] `build/sign.ps1` הורץ ידנית עם טוקן ה-USB מחובר (ראו התיעוד בקובץ עצמו)
- [ ] אימות חתימה: `signtool verify /pa Scriptly-PC-Setup-<version>.exe`
