from __future__ import annotations

import re
import unicodedata

# Ordered from the most specific commercial/service names to broader domains.
# The first match wins, which avoids a generic word overriding a known brand.
_KEYWORD_EMOJI: tuple[tuple[tuple[str, ...], str], ...] = (
    (("netflix", "نتفلكس", "نتفليكس", "movie", "movies", "cinema", "فيلم", "افلام", "أفلام", "مسلسلات"), "🎬"),
    (("youtube", "يوتيوب", "video", "فيديو", "مونتاج", "stream", "بث"), "📺"),
    (("spotify", "سبوتفاي", "music", "موسيقى", "اغاني", "أغاني", "audio", "صوت"), "🎵"),
    (("design", "designer", "تصميم", "مصمم", "canva", "كانفا", "photoshop", "فوتوشوب", "illustrator", "الستريتور"), "🎨"),
    (("medical", "medicine", "health", "طبي", "طبية", "طب", "صحة", "تمريض", "صيدلة", "اسنان", "أسنان"), "🩺"),
    (("ai", "artificial intelligence", "ذكاء اصطناعي", "الذكاء الاصطناعي", "chatgpt", "gpt", "gemini", "جيمناي", "claude", "كلود"), "🤖"),
    (("education", "study", "student", "تعليم", "دراسة", "طلاب", "طالب", "جامعة", "اكاديمي", "أكاديمي", "course", "كورس"), "📚"),
    (("programming", "developer", "coding", "python", "برمجة", "مطور", "كود", "github", "جيت هب"), "💻"),
    (("cloud", "hosting", "server", "سحابة", "استضافة", "سيرفر", "vps"), "☁️"),
    (("security", "vpn", "حماية", "امن", "أمن", "خصوصية"), "🔐"),
    (("email", "mail", "ايميل", "إيميل", "بريد"), "📧"),
    (("book", "books", "كتاب", "كتب", "مكتبة", "ebook"), "📖"),
    (("language", "english", "arabic", "لغة", "انكليزي", "إنكليزي", "عربي", "ترجمة", "translate"), "🌐"),
    (("gaming", "game", "games", "العاب", "ألعاب", "لعبة", "playstation", "بلايستيشن", "xbox"), "🎮"),
    (("finance", "payment", "wallet", "مال", "مالي", "دفع", "محفظة", "محاسبة"), "💳"),
    (("business", "marketing", "تجارة", "اعمال", "أعمال", "تسويق", "متجر"), "📈"),
    (("document", "office", "word", "excel", "ملف", "مستند", "اوفيس", "أوفيس", "وورد", "اكسل", "إكسل"), "📄"),
    (("photo", "image", "صور", "صورة", "تصوير", "camera", "كاميرا"), "📷"),
    (("sport", "sports", "fitness", "رياضة", "لياقة", "gym", "جيم"), "🏋️"),
    (("food", "restaurant", "طعام", "اكل", "أكل", "مطعم"), "🍽️"),
    (("travel", "trip", "سفر", "رحلة", "سياحة"), "✈️"),
    (("legal", "law", "قانون", "قانوني", "محاماة"), "⚖️"),
    (("account", "subscription", "اشتراك", "حساب", "باقة", "premium", "بريميوم"), "📦"),
)

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06FF]+", re.UNICODE)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": ""}))
    return " ".join(_NON_WORD.sub(" ", text).split())


def smart_emoji(name: str, *, default: str = "✨") -> str:
    """Return a deterministic emoji from Arabic/English service keywords.

    The mapper is intentionally local and dependency-free so adding a category
    never waits for a network call and cannot interrupt an FSM transaction.
    """

    normalized = _normalize(name)
    if not normalized:
        return default
    padded = f" {normalized} "
    for keywords, emoji in _KEYWORD_EMOJI:
        for keyword in keywords:
            normalized_keyword = _normalize(keyword)
            if not normalized_keyword:
                continue
            # Exact token/phrase matching avoids accidental matches such as
            # English "ai" inside an unrelated word.
            if f" {normalized_keyword} " in padded:
                return emoji
    return default
