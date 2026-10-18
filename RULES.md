# כללי EuroLeague Fantasy Challenge — מצב קלאסי

נקראו ב־12 באוקטובר 2026 ממדריך החוקים שאליו מפנה האפליקציה הרשמית. המערכת מנתחת PIR ומציעה חלופות סגל תחת תקציב ומגבלות המחזור. עם נתונים מלאים היא מציעה חמישייה חוקית, קפטן, שחקן שישי וספסל. מדד ההשוואה עדיין אינו תחזית ניקוד פנטזי מלאה או מאומתת.

| נושא | הכלל שפורסם |
| --- | --- |
| תקציב פתיחה | 100 קרדיטים |
| סגל | 4 גארדים, 4 פורוורדים, 2 סנטרים ומאמן |
| מגבלת קבוצה | עד 6 מאותה קבוצת יורוליג |
| חמישיות אפשריות — גארדים / פורוורדים / סנטרים | 2–2–1, 1–2–2, 2–1–2, 1–3–1, 3–1–1 |
| קפטן | מתוך החמישייה; ניקוד כפול |
| חמישייה, שחקן שישי ומאמן | 100% מהניקוד |
| ספסל | 50% מהניקוד |
| חילופים בתוך מחזור | בין מקבצי משחקים יומיים; שחקן חדש או קפטן חדש צריכים עדיין לא לשחק |
| העברות בין מחזורים | עד 4, כולל החלפת מאמן; ללא הגבלה בשלבי הסיום וחלונות מיוחדים |
| מחירים | משתנים אחרי מחזור לפי ביצועי השחקן ושוויו הקודם; אין במדריך נוסחה מלאה לשחזור המחיר |

ניקוד שחקן כולל: נקודות, ריבאונדים, אסיסטים, חטיפות, חסימות ועבירות שסחט (+1 לפעולה); החטאות שדה ועונשין, איבודים, חסימות שספג ועבירות שביצע (−1 לפעולה). כלולים הארכות. הקבוצה המנצחת מקבלת בונוס של 10% לניקוד השחקן. בסיס הפעולות תואם להגדרת PIR, אך **PIR לבדו אינו הניקוד הסופי** אחרי בונוס ניצחון, קפטן וספסל.

המקור מפרסם גם תקציב פתיחה מוגדל למי שנרשם אחרי תחילת העונה: 100 + ‏0.3 לכל מחזור שכבר שוחק. מאחר ששווי הקבוצה משתנה, אין להניח שהתקציב הנוכחי של משתמש קיים הוא 100.

ניקוד מאמן תלוי בניצחון / הפסד, הפרש ונוכחות הארכה. לצורך דירוג חלופות, הוא מוערך באופן מחקרי מתוך הפרשי התוצאות של הקבוצה ויריבתה. טבלת המקור מכילה גבול ניסוח חופף ב־20 נקודות; מדד המאמן משתמש בגבול השמרני כשדגימת החיזוי נופלת בדיוק על 20; אין בכך קביעה של פירוש החוק הרשמי.

מדריך החוקים הוא דף מתעדכן, ללא מזהה עונה מחייב. חלונות ההעברות המיוחדים והתאריכים המופיעים בו לא הוזנו כאילוצים אוטומטיים. לפני בניית הרכב או תכנון העברות יש לאמת את הגדרות העונה הפעילה והמחזור מול המשחק.

מקורות שנקראו:

- [Classic mode](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode)
- [Initial team](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode/initial-team)
- [Managing your team](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode/managing-your-team)
- [Players scoring](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode/players-scoring)
- [Coach scoring](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode/coach-scoring)
- [Quotations and price variations](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode/quotations-and-price-variations)
- [Schedule](https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode/schedule)

מחירים וזמינות: נתיב שוק השחקנים בשרת שהאפליקציה הרשמית משתמשת בו החזיר `HTTP 401 Unauthorized`. לא נמצאו בסביבת העבודה חיבור או משתנה פנטזי קיימים. גישת GitHub אינה הרשאה לשרת המשחק. עד לחיבור מורשה ומיפוי מאומת של מזהי השחקנים, משתמשים ב־CSV/JSON עם מקור ותאריך; אין להזין סיסמה או טוקן בצ'אט.

עדכון מ־12 באוקטובר 2026: חיבור מחירים מורשה אומת ב־Render. נתוני הסגל, התקציב, מגבלת המועדון ומספר החילופים נקראים מהחשבון ומהמחזור הנוכחי. חלופות העברות נשוות לתמונת הסגל בתחילת המחזור (`latest_snapshot`), כולל ההתאמה לשחקנים שאינם פעילים, כפי שעושה הלקוח הרשמי. בסבב יצירת הקבוצה ההעברות בלתי מוגבלות לפי הגדרת הלקוח. כל הקריאות לחשבון הן GET; ביצוע השינויים נשאר במשחק עצמו. בונוס ניצחון לשחקנים עדיין אינו כלול במדד החיזוי.

בסיס ההמלצות השבועיות הוא הסגל הסגור של המחזור האחרון ששוחק, הנקרא במפורש מהנתיב של המחזור הקודם. הסגל שנערך כבר למחזור הבא מוצג כתכנון נפרד. שחקן שכבר הוכנס בתכנון אינו מתואר כשחקן שהיה בסגל הסגור. שווי הסגל המקורי מחושב במחירי היום, והחלופות כפופות לתקציב ולמגבלות המעודכנים.

### Surprise picks (experimental)

The separate top three surprise picks rank upside per current credit, outside the nine
regular positional picks. Upside is `(recent five-appearance mean PIR + mean of the
best two PIR performances in that same history) / 2 × opponent positional matchup
index`. This is a ranking heuristic, not a probability of a round-leading performance.
Only pre-round history is used. Candidates require at least three recent appearances,
15 average minutes, an ordinary scout score of at least 8, an opponent index above 1,
and a positive price verified for the round. Out/doubtful players are excluded;
unknown availability remains visibly unverified. No fixed price cap is applied.
