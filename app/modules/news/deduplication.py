"""Text candidate selection and conservative guards for hybrid deduplication."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
import unicodedata

DEDUPLICATION_WINDOW = timedelta(hours=48)
_TYPOGRAPHY = str.maketrans({'«': '"', '»': '"', '“': '"', '”': '"',
                           '‘': "'", '’': "'", '–': '-', '—': '-'})


def normalized_body(text: str) -> str:
    """Keep words, order, numbers, negations and punctuation intact."""
    return ' '.join(unicodedata.normalize('NFC', text).translate(_TYPOGRAPHY).lower().split())


@dataclass(frozen=True)
class SaveResult:
    outcome: Literal['inserted', 'updated', 'unchanged', 'duplicate']
    original_id: str | None = None
    original_url: str | None = None
    reason: str | None = None
    text_similarity: float | None = None
    embedding_similarity: float | None = None
    limitation: str | None = None


# Starting operating thresholds; semantic similarity alone never removes news.
TEXT_SIMILARITY_THRESHOLD = 0.85
EMBEDDING_SIMILARITY_THRESHOLD = 0.97


def character_similarity(left: str, right: str) -> float:
    """Ordered matching characters, normalized by both full text lengths."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def hybrid_text_similarity(left: str, right: str) -> float | None:
    """Return a candidate score only when conservative factual guards pass.

    This is a lexical safeguard, not a factual entailment model. Ambiguous
    additions and removals are retained; small wording substitutions can pass.
    """
    import re
    from difflib import SequenceMatcher
    a, b = normalized_body(left), normalized_body(right)
    if not a or not b or min(len(a), len(b)) / max(len(a), len(b)) < TEXT_SIMILARITY_THRESHOLD:
        return None
    score = character_similarity(a, b)
    if score < TEXT_SIMILARITY_THRESHOLD:
        return None
    numbers = r'(?<!\w)[+\-−]?\d+(?:[.,:/-]\d+)*\s*%?'
    if re.findall(numbers, a) != re.findall(numbers, b):
        return None
    # Names are intentionally case-sensitive at extraction, including quoted names.
    def names(text):
        words = re.findall(r'\b[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z]*(?:-[А-ЯЁA-Zа-яёa-z]+)*\b', text)
        quoted = re.findall(r'[«“"]([^»”"\n]+)[»”"]', text)
        return [normalized_body(w) for w in words + quoted]
    if names(left) != names(right):
        return None
    protected = (
        'не', 'ни', 'нет', 'без', 'нельзя', 'никогда', 'млн', 'млрд', 'трлн',
        'тыс', 'руб', 'рублей', 'доллар', 'евро', 'процент', 'сегодня', 'вчера', 'завтра',
        'январ', 'феврал', 'март', 'апрел', 'мая', 'май', 'июн', 'июл', 'август',
        'сентябр', 'октябр', 'ноябр', 'декабр', 'понедельник', 'вторник', 'сред',
        'четверг', 'пятниц', 'суббот', 'воскресен', 'планир', 'ожида', 'прогноз',
        'предполага', 'намер', 'возмож', 'вероят', 'может', 'могут', 'решил', 'решен',
        'одобр', 'отклони', 'утверд', 'отмен', 'подпис', 'заключ', 'заверш', 'приостанов',
        'увелич', 'сниз', 'снижен', 'сократ', 'повыс', 'повыш', 'куп', 'покуп',
        'прода', 'продал', 'выро', 'рост', 'упал', 'паден', 'утрат', 'вступ', 'отказ',
    )
    def markers(text):
        return [w for w in re.findall(r'\w+', text) if any(w.startswith(p) for p in protected)]
    if markers(a) != markers(b):
        return None
    # Every sentence must have a counterpart. A new sentence is new information,
    # even when it occupies less than 15% of the complete article.
    split = r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«"\d])'
    sentences_a, sentences_b = re.split(split, left.strip()), re.split(split, right.strip())
    if len(sentences_a) != len(sentences_b):
        return None
    # Standalone additions/deletions are only allowed for attribution/connectors.
    incidental = {'по', 'его', 'ее', 'её', 'словам', 'как', 'отмечает', 'сообщает',
                  'пишет', 'издание', 'также', 'при', 'этом', 'же', 'и', 'а', 'что'}
    for old, new in zip(sentences_a, sentences_b):
        old, new = normalized_body(old), normalized_body(new)
        if character_similarity(old, new) < TEXT_SIMILARITY_THRESHOLD:
            return None
        words_a, words_b = re.findall(r'\w+', old), re.findall(r'\w+', new)
        for tag, i, j, k, l in SequenceMatcher(None, words_a, words_b, autojunk=False).get_opcodes():
            if tag in ('insert', 'delete'):
                if (set(words_a[i:j]) | set(words_b[k:l])) - incidental:
                    return None
            elif tag == 'replace' and max(j-i, l-k) > 3:
                return None
    return score
