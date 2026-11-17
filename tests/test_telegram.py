import json

import httpx
import pytest

from gym_coach.telegram import TelegramClient, TelegramError, pick_photo, split_text

TOKEN = "123:SECRET"
ME = 42


def make(handler, **kw):
    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    tg = TelegramClient(TOKEN, ME, client=http, sleep=sleeps.append, **kw)
    return tg, sleeps


def msg(uid, user, text=None, **extra):
    m = {"from": {"id": user}, "chat": {"id": user}, **extra}
    if text is not None:
        m["text"] = text
    return {"update_id": uid, "message": m}


def test_other_users_are_dropped_and_offset_advances():
    seen = []

    def handler(req):
        seen.append(json.loads(req.read()))
        result = [msg(5, 99, "hi"), msg(6, ME, "yo")]
        return httpx.Response(200, json={"ok": True, "result": result})

    tg, _ = make(handler)
    got = tg.get_updates()
    assert [u.text for u in got] == ["yo"]
    assert tg.offset == 7
    tg.get_updates()
    assert seen[1]["offset"] == 7


def test_network_error_pauses_and_does_not_crash():
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    tg, sleeps = make(handler)
    assert tg.get_updates() == []
    assert len(sleeps) == 1 and sleeps[0] > 0


def test_error_message_has_no_token():
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    tg, _ = make(handler)
    with pytest.raises(TelegramError) as ei:
        tg.send_message(ME, "hi")
    assert TOKEN not in str(ei.value)


def test_photo_picks_largest_within_1280():
    sizes = [
        {"file_id": "s", "width": 90, "height": 90},
        {"file_id": "m", "width": 800, "height": 600},
        {"file_id": "l", "width": 1280, "height": 960},
        {"file_id": "xl", "width": 2560, "height": 1920},
    ]
    assert pick_photo(sizes) == "l"
    assert pick_photo([{"file_id": "x", "width": 3000, "height": 2000}]) == "x"
    assert pick_photo([]) is None


def test_photo_update_yields_file_id():
    photo = [
        {"file_id": "a", "width": 100, "height": 100},
        {"file_id": "b", "width": 1000, "height": 700},
    ]

    def handler(req):
        result = [msg(1, ME, photo=photo, caption="lunch")]
        return httpx.Response(200, json={"ok": True, "result": result})

    tg, _ = make(handler)
    (u,) = tg.get_updates()
    assert u.photo_file_id == "b" and u.caption == "lunch"


def test_long_text_is_split():
    parts = split_text("a" * 9000)
    assert all(len(p) <= 4000 for p in parts) and "".join(parts) == "a" * 9000
    lines = "\n".join(["x" * 100] * 100)
    assert all(len(p) <= 4000 for p in split_text(lines))


def test_send_message_posts_each_chunk():
    bodies = []

    def handler(req):
        bodies.append(req.read())
        return httpx.Response(200, json={"ok": True, "result": {}})

    tg, _ = make(handler)
    tg.send_message(ME, "a" * 8500)
    assert len(bodies) == 3


def test_download_file_returns_bytes():
    def handler(req):
        if req.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "p/1.jpg"}})
        assert req.url.path.endswith("/p/1.jpg")
        return httpx.Response(200, content=b"JPEGDATA")

    tg, _ = make(handler)
    assert tg.download_file("f") == b"JPEGDATA"


def _private(uid, user, text="t"):
    return {"update_id": uid, "message": {
        "from": {"id": user}, "chat": {"id": user, "type": "private"}, "text": text}}


def _client(handler, owner, paired):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramClient(TOKEN, owner, client=http, on_pair=paired.append)


def test_pairing_first_private_sender_then_others_ignored():
    sent = []

    def handler(req):
        body = json.loads(req.read())
        if req.url.path.endswith("sendMessage"):
            sent.append(body["text"])
            return httpx.Response(200, json={"ok": True, "result": {}})
        grp = {"update_id": 1, "message": {"from": {"id": 7}, "chat": {"id": -5, "type": "group"},
                                           "text": "g"}}
        return httpx.Response(200, json={"ok": True,
                                         "result": [grp, _private(2, 11), _private(3, 12)]})

    paired = []
    got = _client(handler, None, paired).get_updates()
    assert paired == [11]
    assert [u.update_id for u in got] == [2]
    assert sent == ["Paired with this account. I will answer only you."]


def test_group_message_never_pairs():
    def handler(req):
        m = {"from": {"id": 7}, "chat": {"id": -5, "type": "group"}, "text": "g"}
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 1, "message": m}]})

    paired = []
    assert _client(handler, None, paired).get_updates() == [] and paired == []


def test_set_owner_overrides_pairing():
    def handler(req):
        return httpx.Response(200, json={"ok": True, "result": [_private(1, 7)]})

    paired = []
    assert _client(handler, ME, paired).get_updates() == [] and paired == []


def test_default_client_has_explicit_timeouts_and_keeps_its_connection():
    from gym_coach.telegram import POLL_TIMEOUT_S, new_http_client
    c = new_http_client()
    assert c.timeout.read == POLL_TIMEOUT_S + 10
    assert c.timeout.connect == 10 and c.timeout.write == 10 and c.timeout.pool == 10
    assert c.headers.get("connection") != "close"  # a new TLS handshake fails 1 in 7 here
    c.close()


# Task 14f: a send that cannot connect is tried again (pauses 1, 3, 8 s), never once answered

def _flaky(fails, ok_response, exc=httpx.ConnectError):
    """A handler that raises `exc` `fails` times, then answers with `ok_response()`."""
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if len(calls) <= fails:
            raise exc("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF", request=req)
        return ok_response()
    return handler, calls


def _ok():
    return httpx.Response(200, json={"ok": True, "result": {}})


def test_send_that_fails_twice_then_works_delivers_once():
    handler, calls = _flaky(2, _ok)
    tg, sleeps = make(handler)
    tg.send_message(ME, "hi")
    assert len(calls) == 3 and sleeps == [1, 3]


def test_send_gives_up_after_four_tries_with_the_cause_and_no_token():
    handler, calls = _flaky(99, _ok)
    tg, sleeps = make(handler)
    with pytest.raises(TelegramError) as ei:
        tg.send_message(ME, "hi")
    assert len(calls) == 4 and sleeps == [1, 3, 8]
    assert "UNEXPECTED_EOF" in str(ei.value) and TOKEN not in str(ei.value)


def test_send_is_not_repeated_once_telegram_answered():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"ok": False, "description": "Bad Request"})

    tg, sleeps = make(handler)
    with pytest.raises(TelegramError):
        tg.send_message(ME, "hi")
    assert len(calls) == 1 and sleeps == []


def test_send_is_not_repeated_after_a_read_timeout():
    handler, calls = _flaky(1, _ok, exc=httpx.ReadTimeout)
    tg, _ = make(handler)
    with pytest.raises(TelegramError):
        tg.send_message(ME, "hi")
    assert len(calls) == 1


def test_album_and_single_picture_are_tried_again():
    handler, calls = _flaky(1, _ok)
    tg, sleeps = make(handler)
    tg.send_pictures(ME, [b"a", b"b"], "cap")
    tg.send_pictures(ME, [b"a"], "cap")
    assert [p.rsplit("/", 1)[1] for p in calls] == ["sendMediaGroup", "sendMediaGroup",
                                                     "sendPhoto"]
    assert sleeps == [1]


def test_download_is_tried_again():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if len(calls) in (1, 3):
            raise httpx.ConnectTimeout("slow", request=req)
        if req.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "p/1.jpg"}})
        return httpx.Response(200, content=b"JPEGDATA")

    tg, sleeps = make(handler)
    assert tg.download_file("f") == b"JPEGDATA"
    assert len(calls) == 4 and sleeps == [1, 1]


def test_poll_is_not_retried_inside_the_call():
    handler, calls = _flaky(99, _ok)
    tg, sleeps = make(handler)
    assert tg.get_updates() == []
    assert len(calls) == 1 and len(sleeps) == 1
