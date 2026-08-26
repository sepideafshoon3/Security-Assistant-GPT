import collections
import string

STOPWORDS = {
    # انگلیسی
    "the", "and", "for", "with", "that", "this", "from", "have", "there",
    "you", "your", "are", "was", "were", "but", "not", "can", "cannot",
    "will", "would", "should", "into", "onto", "about", "above", "below",
    "under", "over", "between", "within", "without", "here", "there",
    "what", "when", "where", "why", "how", "who", "whom",
    # تر / عمومی
    "من", "ما", "تو", "شما", "اون", "او", "این", "آن", "که", "برای", "به",
    "در", "از", "روی", "تا", "یا", "اگر", "ولی", "اما", "هیچ", "چیز",
}

def extract_keywords_from_messages(
    messages: list[dict[str, str]],
    top_k: int = 8,
) -> list[str]:
    """
    خیلی ساده:
      - فقط پیام‌های user
      - tokenize روی A-Z0-9_.- (برای domain / CVE / command)
      - حذف stopword + کلمات کوتاه
      - برگردوندن top_k بر اساس frequency
    """
    text_chunks: list[str] = []

    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        text_chunks.append(str(content))

    full_text = " ".join(text_chunks).lower()

    # اجازه بده domain / CVE / command ها هم بمونن:
    tokens = re.findall(r"[a-z0-9_.:/-]+", full_text)

    counter = collections.Counter(
        t for t in tokens
        if len(t) >= 3 and t not in STOPWORDS
    )

    keywords = [t for t, _ in counter.most_common(top_k)]
    return keywords
