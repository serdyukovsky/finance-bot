from bot.parser import match_category, parse

KEYS = {"альфа", "сбер", "нал", "кальфа", "ксбер", "кредит"}
CATS = [
    ("Продукты", ["магнит", "пятёрочка", "мария-ра", "продукты"]),
    ("Кафе и доставка", ["кафе", "кофе", "яндекс еда"]),
    ("Транспорт", ["такси", "автобус"]),
    ("Кот", ["корм", "кот"]),
]


def test_expense_default_account():
    p = parse("450 магнит", KEYS)
    assert p.kind == "expense" and p.amount == 450 and p.account_key is None
    assert p.comment == "магнит"


def test_income():
    p = parse("+15000 лендинг для клиента", KEYS)
    assert p.kind == "income" and p.amount == 15000
    assert p.comment == "лендинг для клиента"


def test_account_override_anywhere():
    p = parse("450 альфа такси", KEYS)
    assert p.account_key == "альфа" and p.comment == "такси"


def test_thousands_suffix_and_decimal():
    assert parse("2к кафе", KEYS).amount == 2000
    assert parse("1,5к", KEYS).amount == 1500
    assert parse("99.90 кофе", KEYS).amount == 99.9


def test_spaced_thousands():
    p = parse("10 545 > сбер", KEYS)
    assert p.amount == 10545 and p.kind == "transfer" and p.dest_key == "сбер"


def test_transfer_with_source_and_comment():
    p = parse("5000 нал > альфа вернул", KEYS)
    assert p.account_key == "нал" and p.dest_key == "альфа" and p.comment == "вернул"


def test_not_amount():
    assert parse("привет", KEYS) is None
    assert parse("0 кафе", KEYS) is None


def test_small_number_word_not_thousands():
    p = parse("450 2 шаурмы", KEYS)
    assert p.amount == 450


def test_category_stem_match():
    p = parse("890 пятерочке", KEYS)
    assert match_category(p.words, p.comment, CATS) == "Продукты"
    p = parse("300 магните", KEYS)
    assert match_category(p.words, p.comment, CATS) == "Продукты"


def test_category_phrase_and_name():
    p = parse("700 яндекс еда суши", KEYS)
    assert match_category(p.words, p.comment, CATS) == "Кафе и доставка"
    p = parse("500 кот корм", KEYS)
    assert match_category(p.words, p.comment, CATS) == "Кот"


def test_no_category():
    p = parse("1200 непонятно", KEYS)
    assert match_category(p.words, p.comment, CATS) is None
