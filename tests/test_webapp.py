"""Проверка подписи initData мини-приложения."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from bot.webapp import check_init_data

TOKEN = "123:abc"


def signed(user_id=1, auth_date=None, token=TOKEN):
    pairs = {"auth_date": str(auth_date or int(time.time())), "query_id": "q", "user": json.dumps({"id": user_id})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_valid_signature_gives_user():
    assert check_init_data(signed(42), TOKEN) == {"id": 42}


def test_wrong_token_tampered_or_old_rejected():
    assert check_init_data(signed(42, token="other"), TOKEN) is None
    assert check_init_data(signed(42).replace("%22id%22%3A+42", "%22id%22%3A+43"), TOKEN) is None
    assert check_init_data(signed(42, auth_date=int(time.time()) - 2 * 86400), TOKEN) is None
    assert check_init_data("", TOKEN) is None
