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
