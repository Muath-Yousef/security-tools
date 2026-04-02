# ID Exposure Scanner

أداة سطر أوامر بلغة Python لتحليل مدى ظهور **معرّفات اختبارية** على الإنترنت، ضمن بيئة معزولة (Docker)، كجزء من عمليات **تقييم التعرض الأمني** (Exposure Assessment).

> ⚠️ **تنبيه قانوني**: هذه الأداة مصممة حصريًا للاستخدام داخل بيئات اختبار أمنية معتمدة. لا تستخدمها على بيانات حقيقية دون الحصول على التفويض القانوني المناسب.

---

## 🏗️ هيكل المشروع

```
id-exposure-scanner/
├── main.py                    # نقطة الدخول الرئيسية (CLI)
├── config.py                  # إدارة الإعدادات (.env)
├── modules/
│   ├── __init__.py
│   ├── normalizer.py          # توحيد تنسيق المدخلات
│   ├── search_engines.py      # البحث في Google و Bing
│   ├── platforms.py           # البحث في المنصات العامة
│   └── reporter.py            # إنشاء تقارير JSON/CSV مع تجزئة SHA-256
├── Dockerfile                 # بناء الحاوية المعزولة
├── docker-compose.yml         # تشغيل الحاوية مع إعدادات الأمان
├── requirements.txt           # المكتبات المطلوبة
├── .env.example               # قالب متغيرات البيئة
└── output/                    # مجلد المخرجات (تقارير + سجلات)
```

---

## ⚙️ المتطلبات

- Python 3.11+
- Docker و Docker Compose (للتشغيل المعزول)

### المكتبات المستخدمة

| المكتبة | الوظيفة |
|---------|---------|
| `requests` | طلبات HTTP |
| `beautifulsoup4` + `lxml` | تحليل HTML |
| `pandas` | إنشاء تقارير CSV |
| `loguru` | نظام تسجيل متقدم |
| `python-dotenv` | تحميل متغيرات البيئة |

---

## 🚀 التشغيل

### الطريقة 1: Docker (موصى بها)

```bash
# 1. نسخ ملف البيئة
cp .env.example .env

# 2. بناء الحاوية
docker compose build

# 3. تشغيل الفحص
docker compose run scanner "1234567890"

# مع خيارات إضافية
docker compose run scanner "1234567890" --max-results 10 --log-level DEBUG
```

### الطريقة 2: Python مباشرة

```bash
# 1. إنشاء بيئة افتراضية
python3 -m venv venv
source venv/bin/activate

# 2. تثبيت المكتبات
pip install -r requirements.txt

# 3. نسخ ملف البيئة
cp .env.example .env

# 4. تشغيل الفحص
python main.py "1234567890"
```

---

## 📋 خيارات سطر الأوامر

```
usage: id-exposure-scanner [-h] [-o OUTPUT_DIR] [-m MAX_RESULTS]
                           [--log-level {DEBUG,INFO,WARNING,ERROR}]
                           [--skip-search-engines] [--skip-platforms]
                           identifier

positional arguments:
  identifier            المعرّف الرقمي / الرمز المراد فحصه

optional arguments:
  -o, --output-dir      مجلد المخرجات (افتراضي: ./output)
  -m, --max-results     عدد النتائج الأقصى لكل مصدر (افتراضي: 20)
  --log-level           مستوى التسجيل: DEBUG, INFO, WARNING, ERROR
  --skip-search-engines تخطّي محركات البحث (Google, Bing)
  --skip-platforms      تخطّي المنصات العامة (GitHub, Reddit, إلخ)
```

### أمثلة

```bash
# فحص رقم هاتف اختباري
python main.py "+971501234567"

# فحص مع مخرجات مفصّلة
python main.py "TEST-ID-2024" --log-level DEBUG

# فحص المنصات فقط (تخطّي محركات البحث)
python main.py "user@test.com" --skip-search-engines

# تحديد الحد الأقصى للنتائج
python main.py "ABC123" -m 5 -o ./my_reports
```

---

## 📦 المخرجات

بعد كل عملية فحص، يتم إنشاء ثلاثة ملفات في مجلد `output/`:

| الملف | الوصف |
|-------|-------|
| `scan_<id>_<timestamp>.json` | التقرير الكامل بتنسيق JSON |
| `scan_<id>_<timestamp>.csv` | ملخص النتائج بتنسيق CSV |
| `scan_<id>_<timestamp>.sha256` | تجزئات SHA-256 للتحقق من سلامة الملفات |

### نموذج JSON

```json
{
  "meta": {
    "identifier": "1234567890",
    "normalization": {
      "original": "1234567890",
      "canonical": "1234567890",
      "variants": ["1234567890", "123-456-7890", "\"1234567890\""]
    },
    "scan_timestamp": "20260401T220000Z",
    "total_results": 15
  },
  "results": [
    {
      "source": "google",
      "query": "\"1234567890\"",
      "title": "Example Result Title",
      "link": "https://example.com/page",
      "snippet": "Context text surrounding the identifier...",
      "timestamp": "2026-04-01T22:00:00+00:00"
    }
  ]
}
```

---

## ⚠️ ملاحظات لتحسين الدقة (Accuracy & Rate Limits)

نظراً لأن الأداة تعتمد بشدة على تقنيات الاستخلاص (Scraping) والـ Dorking، قد تواجه حجب متكرر (Rate Limit - HTTP 429) من قبل المنصات وخاصة Google عند العمل من داخل الحاويات (Containers). للحصول على أفضل وأدق النتائج المستقرة، يُنصح بشدة بتوفير مفاتيح الـ API التالية في ملف `.env`:

1. **`BING_API_KEY`**: سيتجاوز الفحص التقليدي لـ Bing ويستخدم الواجهة البرمجية المباشرة (Bing Web Search API) مما يمنع الحجب ويعطي نتائج أدق.
2. **`HIBP_API_KEY`**: للحصول على معلومات اختراق/تسريبات البريد الإلكتروني (عند استخدام خيار `--search-emails`) بشكل كامل.
3. **`TRUECALLER_API_KEY`**: في حال توفر مفتاح مؤسسي، سيقوم بجلب الاسم والحالة المرتبطة برقم الهاتف مباشرة وتقليل الاعتماد على محركات البحث.
4. **`GITHUB_TOKEN`**: ويرفع حد واجهة برمجة (API) الخاصة بـ Github وتسمح بالبحث داخل الكود.

---

## 🔍 مصادر البحث

### محركات البحث
- **Google** — بحث HTML مع عوامل بحث دقيقة
- **Bing** — بحث HTML أو Bing API v7 (عند توفر `BING_API_KEY`)

### المنصات العامة
- **GitHub** — بحث في الكود والمستخدمين (Public API)
- **Reddit** — بحث عبر واجهة JSON العامة
- **GitLab** — بحث في المشاريع العامة
- **DuckDuckGo** — Instant Answer API
- **Paste Sites** — بحث في pastebin.com، dpaste.org عبر Google dorking

---

## 🔒 الأمان

تتضمن حاوية Docker إعدادات أمان مشددة:

- `read_only: true` — نظام ملفات للقراءة فقط
- `no-new-privileges: true` — منع تصعيد الصلاحيات
- `tmpfs: /tmp` — ذاكرة مؤقتة فقط
- **تأخير تلقائي** بين الطلبات (`REQUEST_DELAY`) لاحترام حدود الخدمة
- **تسجيل كامل** لكل طلب مع الزمن والنتيجة

---

## 📝 التسجيل (Logging)

- **السجلات على الشاشة**: ملونة مع مستوى قابل للتعديل
- **سجلات الملفات**: تُحفظ في `output/scanner_YYYY-MM-DD.log`
  - تُدور يوميًا وتُحتفظ لمدة 30 يومًا
  - مستوى `DEBUG` دائمًا في الملفات
- كل طلب HTTP يُسجَّل مع: المصدر، الاستعلام، الزمن، الحالة، عدد النتائج

---

## 📄 الترخيص

هذه الأداة مخصصة للاستخدام الداخلي في بيئات الاختبار الأمني فقط.
