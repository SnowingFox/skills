"""Tests for orca_search.py (no network, no Orca: subprocess is faked). Run: python3 test_orca_search.py"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orca_search as m  # noqa: E402


class P:
    def __init__(self, stdout, code=0):
        self.stdout, self.stderr, self.returncode = stdout, "", code


def fake(script):
    """A subprocess.run stand-in: script maps a key (first matching substring of the joined argv) to stdout or a callable."""
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        line = " ".join(argv)
        for k, v in script:
            if k in line:
                return P(v(argv) if callable(v) else v)
        raise AssertionError(f"unexpected call: {line}")
    run.calls = calls
    return run


def ok(result):
    return json.dumps({"ok": True, "result": result})


def test_search_url():
    u = m.search_url("SK hynix", news=True, when="d", n=5)
    assert "q=SK+hynix" in u and "tbm=nws" in u and "tbs=qdr%3Ad" in u and "num=10" in u, u
    assert "tbm" not in m.search_url("x")


def test_resolve_follows_302_and_shorteners():
    hops = {"https://www.google.com/goto?url=A": "302 https://t.co/x", "https://t.co/x": "301 https://news.example.com/a"}
    run = fake([("goto?url=A", lambda a: hops[a[-1]]), ("t.co/x", lambda a: hops[a[-1]])])
    assert m.resolve("https://www.google.com/goto?url=A", run=run) == "https://news.example.com/a"


def test_resolve_keeps_google_link_on_interstitial():
    run = fake([("goto", "200 ")])
    u = "https://www.google.com/goto?url=B"
    assert m.resolve(u, run=run) == u
    assert len(run.calls) == 2  # retried once


def test_resolve_passes_non_google_links_untouched():
    run = fake([])
    assert m.resolve("https://example.com/x", run=run) == "https://example.com/x"
    assert run.calls == []


def test_browser_resolve_clicks_continue_then_lands():
    state = {"n": 0}

    def get_url(_):
        state["n"] += 1
        return ok({"url": "https://www.google.com/goto?url=C" if state["n"] < 5 else "https://site.example/a"})
    run = fake([(" goto ", ok({"effects": {}})), ("get url", get_url), (" eval ", ok({"result": "clicked"}))])
    assert m.browser_resolve("p1", "https://www.google.com/goto?url=C", run=run, sleep=lambda s: None) == "https://site.example/a"
    assert any("eval" in c for c in run.calls), "Continue button was not tried"


def test_browser_resolve_gives_up():
    run = fake([(" goto ", ok({})), ("get url", ok({"url": "https://www.google.com/goto?url=D"})), (" eval ", ok({"result": "none"}))])
    u = "https://www.google.com/goto?url=D"
    assert m.browser_resolve("p1", u, run=run, wait_s=3, sleep=lambda s: None) == u


def test_orca_error_raises():
    run = fake([("tab", json.dumps({"ok": False, "error": {"code": "browser_no_tab"}}))])
    try:
        m.orca(["tab", "list"], run)
    except RuntimeError as e:
        assert "browser_no_tab" in str(e)
    else:
        raise AssertionError("no error raised")


def test_page_id_reuses_saved_tab_or_creates():
    with tempfile.TemporaryDirectory() as d:
        st = os.path.join(d, "s.json")
        json.dump({"page": "p-old"}, open(st, "w"))
        run = fake([("tab list", ok({"tabs": [{"browserPageId": "p-old"}]}))])
        assert m.page_id(run, st) == "p-old"
        run = fake([("tab list", ok({"tabs": []})), ("tab create", ok({"browserPageId": "p-new"}))])
        assert m.page_id(run, st) == "p-new"
        assert json.load(open(st))["page"] == "p-new"


def test_count_resets_each_day():
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "c")
        json.dump({"date": "2000-01-01", "n": 99, "blocked": True}, open(c, "w"))
        assert m.read_count(c)[1:] == (0, False)
        m.write_count(3, False, c)
        assert m.read_count(c)[1:] == (3, False)
        assert oct(os.stat(c).st_mode & 0o777) == "0o600"


def test_ai_overview_extract():
    md = "Search Results\nAI Overview\n### AI Mode reply\nSK hynix rose 8%.\nYahoo Finance +2\nShow more\nAI responses may include mistakes.\n1. other"
    out = m.ai_overview(md)
    assert "SK hynix rose 8%." in out and "Yahoo Finance +2" not in out and "Show more" not in out, out
    assert m.ai_overview("no overview here") == ""


def test_run_search_marks_blocked_page():
    page = {"url": "https://www.google.com/sorry/index", "blocked": True, "results": []}
    with tempfile.TemporaryDirectory() as d:
        st = os.path.join(d, "s.json")
        json.dump({"page": "p1"}, open(st, "w"))
        orig = m.STATE
        m.STATE = st
        try:
            run = fake([("tab list", ok({"tabs": [{"browserPageId": "p1"}]})), (" goto ", ok({})), (" wait ", ok({})),
                        (" eval ", ok({"result": json.dumps(page)}))])
            res = m.run_search("q", run=run)
        finally:
            m.STATE = orig
    assert res["blocked"] is True and res["results"] == []


def test_block_is_sticky_for_the_day():
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "c")
        m.write_count(1, True, c)
        m.write_count(2, False, c)
        assert m.read_count(c)[1:] == (2, True)


def test_same_query():
    assert m.same_query("https://www.google.com/search?q=SK+hynix&hl=en", "sk hynix")
    assert not m.same_query("https://www.google.com/search?q=ethereum+staking", "bitcoin ETF flows")


def test_lock_excludes_a_second_holder():
    with tempfile.TemporaryDirectory() as d:
        lk = os.path.join(d, "l")
        with m.SearchLock(lk):
            try:
                with m.SearchLock(lk, wait_s=0.5, sleep=lambda s: None):
                    raise AssertionError("second lock acquired")
            except TimeoutError:
                pass
        with m.SearchLock(lk, wait_s=0.5):
            pass


def test_slot_lock_hands_out_different_tabs():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "l")
        with m.SlotLock(tabs=2, base=base) as a, m.SlotLock(tabs=2, base=base, wait_s=0.5, sleep=lambda s: None) as b:
            assert {a.slot, b.slot} == {0, 1}
            try:
                with m.SlotLock(tabs=2, base=base, wait_s=0.5, sleep=lambda s: None):
                    raise AssertionError("third holder got a tab")
            except TimeoutError:
                pass


def test_bump_count_adds_under_lock():
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "c")
        assert m.bump_count(False, c) == 1 and m.bump_count(False, c) == 2
        assert m.read_count(c)[1:] == (2, False)


def test_page_id_per_slot_keeps_old_key():
    with tempfile.TemporaryDirectory() as d:
        st = os.path.join(d, "s.json")
        json.dump({"page": "p0"}, open(st, "w"))
        run = fake([("tab list", ok({"tabs": [{"browserPageId": "p0"}]})), ("tab create", ok({"browserPageId": "p1"}))])
        assert m.page_id(run, st, slot=0) == "p0"
        assert m.page_id(run, st, slot=1) == "p1"
        saved = json.load(open(st))
        assert saved["page"] == "p0" and saved["pages"]["1"] == "p1"


def test_close_slot_closes_and_forgets_tab():
    with tempfile.TemporaryDirectory() as d:
        st = os.path.join(d, "s.json")
        json.dump({"page": "p0", "pages": {"0": "p0", "1": "p1"}}, open(st, "w"))
        run = fake([("tab close", ok({"closed": True}))])
        m.close_slot(1, run=run, state=st)
        assert any("p1" in c for c in run.calls), run.calls
        saved = json.load(open(st))
        assert "1" not in saved["pages"] and saved["page"] == "p0"
        m.close_slot(0, run=run, state=st)
        saved = json.load(open(st))
        assert "page" not in saved and saved["pages"] == {}
        m.close_slot(2, run=fake([]), state=st)  # nothing saved for slot 2: no orca call


def test_read_refuses_non_http_urls():
    for u in ("file:///etc/passwd", "javascript:alert(1)", "example.com"):
        try:
            m.main(["--read", u])
        except SystemExit as e:
            assert e.code == 2
        else:
            raise AssertionError(f"accepted {u}")


def test_no_daily_cap_unless_one_is_set():
    """Searches are unlimited by default; ORCA_SEARCH_DAILY_CAP > 0 refuses past that count; a captcha block still refuses."""
    saved = m.COUNT, m.CAP, m.run_search
    with tempfile.TemporaryDirectory() as d:
        try:
            m.COUNT = os.path.join(d, "c.count")
            m.run_search = lambda q, *a, **k: {"query": q, "news": False, "when": None, "blocked": False, "ai_overview": None,
                                               "page": "p0", "page_url": "https://www.google.com/search?q=" + q,
                                               "results": [{"title": "t", "source": "s", "age": "", "snippet": "", "url": "https://e.com", "link": "https://e.com"}]}
            a = argparse.Namespace(query="x", n=10, news=False, when=None, ai=False, resolve_all=False, open=None, json=True, max_chars=100)
            m.write_count(5000, False, m.COUNT)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                m.CAP = 0
                assert m._search(a) == 0
                assert m.read_count(m.COUNT)[1] == 5001
                m.CAP = 40
                assert m._search(a) == 3
                m.CAP = 0
                m.write_count(1, True, m.COUNT)
                assert m._search(a) == 3
        finally:
            m.COUNT, m.CAP, m.run_search = saved


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
    print(f"all tests passed ({len(fns)})")
