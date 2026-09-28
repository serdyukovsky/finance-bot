"""Разбор сообщений вида «450 магнит», «+15000 лендинг», «10545 > сбер».

Чистая логика без сети — покрыта тестами в tests/test_parser.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

AMOUNT_RE = re.compile(
    r"^\s*(?P<sign>[+-])?\s*"
    r"(?P<num>\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(?P<k>к|k|тыс)?(?=\s|>|$)"
    r"(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)

PUNCT_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def norm(s: str) -> str:
    """Нижний регистр, ё→е, без пунктуации по краям."""
    s = s.lower().replace("ё", "е")
    return PUNCT_RE.sub("", s).strip()


@dataclass
class Parsed:
    kind: str  # expense | income | transfer
    amount: float  # всегда положительная
    account_key: str | None = None  # счёт-источник (ключ)
    dest_key: str | None = None  # счёт-получатель для переводов
    comment: str = ""
    words: list[str] = field(default_factory=list)  # нормализованные слова комментария


def parse_amount(text: str):
    m = AMOUNT_RE.match(text)
    if not m:
        return None
    num = m.group("num").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        amount = float(num)
    except ValueError:
        return None
    if m.group("k"):
        amount *= 1000
    if amount <= 0:
        return None
    return m.group("sign") or "", amount, m.group("rest").strip()


def parse(text: str, account_keys: set[str]) -> Parsed | None:
    res = parse_amount(text)
    if res is None:
        return None
    sign, amount, rest = res
    keys = {norm(k) for k in account_keys if k}

    if ">" in rest:
        left, right = rest.split(">", 1)
        src = None
        left_words = left.split()
        if left_words and norm(left_words[0]) in keys:
            src = norm(left_words[0])
        right_words = right.split()
        if not right_words:
            return Parsed("transfer", amount, src, None, "")
        dest = norm(right_words[0])
        comment_words = right_words[1:]
        return Parsed(
            "transfer",
            amount,
            src,
            dest,
            " ".join(comment_words),
            [norm(w) for w in comment_words if norm(w)],
        )

    account = None
    comment_words = []
    for w in rest.split():
        if account is None and norm(w) in keys:
            account = norm(w)
        else:
            comment_words.append(w)
    kind = "income" if sign == "+" else "expense"
    return Parsed(
        kind,
        amount,
        account,
        None,
        " ".join(comment_words),
        [norm(w) for w in comment_words if norm(w)],
    )


def _kw_match(word: str, kw: str) -> bool:
    if word == kw:
        return True
    # «пятерочке» ~ «пятерочка», «магните» ~ «магнит»: общий префикс
    if len(kw) >= 4 and len(word) >= 4:
        stem = kw[: max(4, len(kw) - 2)]
        return word.startswith(stem)
    return False


def match_category(words: list[str], comment: str, categories: list[tuple[str, list[str]]]) -> str | None:
    """categories: [(имя, [ключевые слова])]. Возвращает первое совпадение по порядку."""
    text = " " + " ".join(words) + " "
    for name, keywords in categories:
        kws = [norm(k) for k in keywords if norm(k)] + [norm(name)]
        for kw in kws:
            if " " in kw:
                if f" {kw} " in text:
                    return name
                continue
            if any(_kw_match(w, kw) for w in words):
                return name
    return None
