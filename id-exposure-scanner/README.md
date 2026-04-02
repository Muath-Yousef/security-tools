# ID Exposure Scanner v2

أداة سطر أوامر بلغة Python لتحليل مدى ظهور **معرّفات اختبارية** على الإنترنت، ضمن بيئة معزولة (Docker)، كجزء من عمليات **تقييم التعرض الأمني** (Exposure Assessment).

> ⚠️ **تنبيه قانوني**: هذه الأداة مصممة حصريًا للاستخدام داخل بيئات اختبار أمنية معتمدة.  
> لا تستخدمها على بيانات حقيقية دون الحصول على التفويض القانوني المناسب.

---

## 🆕 ما الجديد في v2؟

| التحسين | التفاصيل |
|---------|---------|
| **كشف CAPTCHA** | الأداة الآن تكتشف صفحات CAPTCHA وتسجّل تحذيراً بدلاً من إرجاع صفر نتائج بصمت |
| **سيلكتورات Google متعددة** | تجرب `div.g` → `div.tF2Cxc` → `div.MjjYud` بالترتيب لمواجهة تغييرات Google المتكررة |
| **DuckDuckGo HTML** | استُبدل Instant Answer API (نتيجة واحدة فقط) بالبحث الحقيقي على `html.duckduckgo.com` |
| **درجة الصلة (Relevance Score)** | كل نتيجة تحصل على درجة 0.0–1.0 بناءً على مدى احتوائها للمعرّف فعلياً |
| **تطبيع الـ URL** | يُزيل معلمات التتبع (`?utm_source`, `?fbclid`…) قبل المقارنة لتفادي تكرار النتائج |
| **Wayback Machine** | يبحث في أرشيف الإنترنت عن صفحات كانت تحتوي المعرّف ثم حُذفت |
| **GitLab Snippets** | يبحث في Snippets بالإضافة إلى Projects |
| **Paste sites محدّثة** | حُذف Ghostbin (معطّل منذ 2021)، أُضيف `paste.fo`, `justpaste.it`, `rentry.co`, `paste.gg` |
| **صيغ هاتفية إضافية** | أقواس `(079) 571-4560`، روابط `wa.me/962…`، صيغة `api.whatsapp.com/send?phone=…` |
| **`--min-relevance`** | خيار جديد لتصفية النتائج ضعيفة الصلة تلقائياً |

---

## 🏗️ هيكل المشروع

```
id-exposure-scanner/
├── main.py                    # نقطة الدخول الرئيسية (CLI)
├── config.py                  # إدارة الإعدادات (.env)
├── modules/
│   ├── __init__.py
│   ├── normalizer.py          # توحيد تنسيق المدخلات وتوليد الصيغ
│   ├── search_engines.py      # Google / Bing / Yahoo / DuckDuckGo
│   ├── platforms.py           # GitHub / Reddit / GitLab / Wayback / paste sites / …
│   ├── email_search.py        # بحث البريد الإلكتروني + HIBP
│   ├── network_check.py       # DNS / WHOIS السلبي
│   └── reporter.py            # تقارير JSON/CSV مع SHA-256
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example               # قالب متغيرات البيئة
└── output/                    # مجلد المخرجات (تُنشأ تلقائياً)
```

---

## ⚙️ المتطلبات

- Python 3.11+  
- Docker + Docker Compose *(للتشغيل المعزول — موصى به)*

### المكتبات الرئيسية

| المكتبة | الوظيفة |
|---------|---------|
| `requests` | طلبات HTTP مع retry تلقائي |
| `beautifulsoup4` + `lxml` | تحليل HTML |
| `pandas` | إنشاء تقارير CSV |
| `loguru` | تسجيل متقدم مع rotation |
| `python-dotenv` | تحميل متغيرات البيئة |

---

## 🚀 التشغيل السريع

### الطريقة 1: Docker (موصى بها)

```bash
# 1. نسخ ملف البيئة وتعديله
cp .env.example .env

# 2. بناء الحاوية
docker compose build

# 3. تشغيل الفحص
docker compose run scanner "00962795714560"

# مع خيارات إضافية
docker compose run scanner "00962795714560" \
  --search-emails \
  --network-scan \
  --min-relevance 0.20 \
  -v
```

### الطريقة 2: Python مباشرة

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py "00962795714560"
```

---

## 📋 خيارات سطر الأوامر

```
usage: id-exposure-scanner [-h] [-o OUTPUT_DIR] [-m MAX_RESULTS]
                           [--log-level {DEBUG,INFO,WARNING,ERROR}]
                           [--skip-search-engines] [--skip-platforms]
                           [-v] [--search-emails] [--network-scan]
                           [--hibp-api-key KEY] [--min-relevance SCORE]
                           identifier
```

| الخيار | القيمة الافتراضية | الوصف |
|--------|-----------------|-------|
| `identifier` | — | المعرّف المراد فحصه (رقم هاتف، هوية، …) |
| `-o / --output-dir` | `./output` | مجلد حفظ التقارير |
| `-m / --max-results` | 20 | عدد النتائج الأقصى لكل مصدر |
| `--log-level` | INFO | مستوى التسجيل |
| `--skip-search-engines` | — | تخطّي Google / Bing / Yahoo / DDG |
| `--skip-platforms` | — | تخطّي المنصات العامة |
| `-v / --verbose` | — | إخراج تشخيصي مفصّل (DEBUG + HTTP) |
| `--search-emails` | — | البحث عن بريد إلكتروني مرتبط |
| `--network-scan` | — | فحص DNS/WHOIS السلبي للنطاقات المستخرجة |
| `--hibp-api-key` | من `.env` | مفتاح HaveIBeenPwned للتحقق من التسريبات |
| `--min-relevance` | 0.0 | تصفية النتائج أقل من هذه الدرجة (0.0–1.0) |

### أمثلة عملية

```bash
# فحص رقم هاتف أردني — المسار الكامل
python main.py "00962795714560"

# فحص المنصات فقط (تخطّي محركات البحث — مفيد عند حجب Google)
python main.py "00962795714560" --skip-search-engines

# فحص مع تصفية النتائج ضعيفة الصلة
python main.py "00962795714560" --min-relevance 0.20

# فحص شامل مع بريد إلكتروني وشبكة
python main.py "00962795714560" \
  --search-emails \
  --network-scan \
  --min-relevance 0.15 \
  --log-level DEBUG

# فحص بالصيغة المحلية فقط (يولّد كل الصيغ تلقائياً)
python main.py "0795714560"
```

---

## 🔍 مصادر البحث الكاملة

### محركات البحث
| المصدر | الطريقة | ملاحظة |
|--------|---------|--------|
| **Google** | HTML scraping | كشف CAPTCHA + سيلكتورات متعددة |
| **Bing** | HTML scraping | يتحول لـ API عند وجود `BING_API_KEY` |
| **Yahoo** | HTML scraping | fallback مفيد عند حجب Google |
| **DuckDuckGo** | HTML scraping | `html.duckduckgo.com` — نتائج حقيقية |

### المنصات
| المصدر | الطريقة | ملاحظة |
|--------|---------|--------|
| **GitHub** | REST API v3 | كود + مستخدمون؛ يدعم `GITHUB_TOKEN` |
| **GitLab** | REST API v4 | مشاريع + **Snippets** (جديد v2) |
| **Reddit** | HTML / OAuth | يدعم `REDDIT_CLIENT_ID` |
| **DuckDuckGo HTML** | HTML scraping | نتائج بحث كاملة |
| **Wayback Machine** | CDX API | ✨ **جديد** — أرشيف صفحات محذوفة |
| **Social Media** | Google dorking | Facebook, Twitter/X, Instagram, LinkedIn, TikTok, Telegram, Snapchat, WhatsApp |
| **Paste Sites** | Google dorking | pastebin, dpaste, paste.fo, justpaste.it, rentry.co, paste.gg, hastebin |
| **MENA Classifieds** | Google dorking | OpenSooq, Haraj, Dubizzle/Bayut, OLX, Waseet, YellowPages |
| **Arabic Forums** | Google dorking | Arabteam2000, ArabsGate |
| **Truecaller** | REST API | يتطلب `TRUECALLER_API_KEY` |

---

## 🎯 نظام درجات الصلة (Relevance Scoring)

كل نتيجة تحصل على درجة من **0.0 إلى 1.0** بحسب:

| المعيار | الدرجة |
|---------|--------|
| المعرّف موجود في عنوان الصفحة | +0.50 |
| المعرّف موجود في مقتطف النتيجة | +0.25 |
| تسلسل الأرقام موجود في أي مكان | +0.15 |
| أحد المتغيرات موجود في النص | +0.10 |

**دليل الاستخدام:**
- `--min-relevance 0.0` — الكل (افتراضي، لمراجعة يدوية)
- `--min-relevance 0.15` — يحذف معظم الضجيج
- `--min-relevance 0.35` — نتائج موثوقة الصلة فقط
- `--min-relevance 0.50` — نتائج عالية الثقة فقط

---

## 🔢 توليد صيغ المعرّف تلقائياً

الأداة تولّد تلقائياً كل الصيغ الممكنة لأي معرّف مدخل.

**مثال على إدخال** `00962795714560`:

```
✔ 00962795714560          (المدخل الأصلي)
✔ 962795714560            (WhatsApp-style)
✔ +962795714560           (دولي)
✔ 0795714560              (محلي أردني)
✔ 795714560               (رقم المشترك فقط)
✔ +962-79-571-4560        (دولي بشرطات)
✔ 079-571-4560            (محلي بشرطات)
✔ (079) 571-4560          (✨ جديد — مبوّبات)
✔ wa.me/962795714560      (✨ جديد — رابط WhatsApp)
✔ "+962795714560"         (اقتباس لبحث دقيق)
✔ "0795714560"            (اقتباس صيغة محلية)
… وصيغ أخرى
```

---

## 📦 المخرجات

بعد كل فحص يُنشئ ثلاثة ملفات في `output/`:

| الملف | الوصف |
|-------|-------|
| `scan_<id>_<timestamp>.json` | التقرير الكامل (meta + results مُرتّبة بالصلة) |
| `scan_<id>_<timestamp>.csv` | ملخص النتائج قابل للفلترة في Excel |
| `scan_<id>_<timestamp>.sha256` | تجزئات SHA-256 لسلامة الأدلة |

### نموذج JSON (v2)

```json
{
  "meta": {
    "identifier": "00962795714560",
    "normalization": {
      "original": "00962795714560",
      "canonical": "00962795714560",
      "id_type": "phone",
      "variants": ["00962795714560", "+962795714560", "0795714560", "..."]
    },
    "scan_timestamp": "20260402T120000Z",
    "total_results": 23
  },
  "results": [
    {
      "source": "google",
      "query": "\"0795714560\"",
      "title": "...",
      "link": "https://opensooq.com/...",
      "snippet": "للتواصل: 0795714560 ...",
      "timestamp": "2026-04-02T12:00:00+00:00",
      "relevance_score": 0.75
    }
  ]
}
```

---

## 🔑 إعداد مفاتيح API (اختياري لكن موصى به)

أضف المفاتيح التالية في ملف `.env` للحصول على نتائج أدق وتجنب الحجب:

```dotenv
# Bing Web Search API — يمنع حجب الـ scraping ويعطي 50 نتيجة/طلب
BING_API_KEY=your_bing_key_here

# GitHub Personal Access Token — يرفع حد GitHub API من 10 إلى 30 req/min
GITHUB_TOKEN=ghp_your_token_here

# Reddit App — للوصول عبر OAuth بدلاً من HTML scraping
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret

# HaveIBeenPwned — للتحقق من تسريبات البريد الإلكتروني
HIBP_API_KEY=your_hibp_key_here

# Truecaller Enterprise API — اسم المشترك وبيانات الخط
TRUECALLER_API_KEY=your_truecaller_key_here
```

---

## ⚠️ تعامل مع حجب Google (CAPTCHA)

إذا واجهت صفر نتائج من Google، الأداة ستسجّل تحذيراً واضحاً:

```
WARNING  [Google] CAPTCHA or bot-detection page returned — results will be empty.
         Consider adding a BING_API_KEY or waiting before retrying.
```

**الحلول:**
1. انتظر 10–15 دقيقة ثم أعد المحاولة
2. استخدم `BING_API_KEY` كبديل موثوق
3. شغّل `--skip-search-engines` للتركيز على المنصات فقط
4. جرّب تشغيل الأداة من عنوان IP مختلف

---

## 🔒 الأمان

تتضمن حاوية Docker إعدادات أمان مشددة:

- `read_only: true` — نظام ملفات للقراءة فقط
- `no-new-privileges: true` — منع تصعيد الصلاحيات
- `tmpfs: /tmp` — ذاكرة مؤقتة فقط في الـ RAM
- **تأخير عشوائي** بين الطلبات (`REQUEST_DELAY_MIN/MAX`) لاحترام حدود الخدمة
- **تسجيل كامل** لكل طلب HTTP مع الزمن والنتيجة
- **SHA-256** لكل ملف مخرجات للحفاظ على سلامة الأدلة

---

## 📝 التسجيل (Logging)

| المستوى | الوجهة | التفاصيل |
|---------|--------|---------|
| `INFO` | الشاشة (ملوّن) | تقدم الفحص والنتائج الرئيسية |
| `DEBUG` | الشاشة (مع `-v`) | طلبات HTTP الخام وتفاصيل التحليل |
| `DEBUG` | ملف يومي | كل شيء، محفوظ 30 يوماً مع rotation |

ملفات السجل: `output/scanner_YYYY-MM-DD.log`

---

## 📄 الترخيص

هذه الأداة مخصصة للاستخدام الداخلي في بيئات الاختبار الأمني المعتمدة فقط.
