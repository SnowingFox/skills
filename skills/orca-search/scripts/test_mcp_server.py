"""Tests for mcp_server.py (no network, no Orca: subprocess is faked). Run: python3 test_mcp_server.py"""
import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_server as m  # noqa: E402


class P:
    def __init__(self, stdout="", code=0, stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, code


def fake(p):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if isinstance(p, Exception):
            raise p
        return p
    run.calls = calls
    return run


def rpc(method, params=None, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}


def test_initialize_echoes_a_known_version_and_carries_instructions():
    r = m.handle(rpc("initialize", {"protocolVersion": "2025-06-18"}))["result"]
    assert r["protocolVersion"] == "2025-06-18" and r["capabilities"] == {"tools": {}}
    assert "google_search first" in r["instructions"] and "untrusted" in r["instructions"]
    assert m.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}))["result"]["protocolVersion"] == m.VERSIONS[0]


def test_notifications_get_no_response():
    assert m.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert m.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 3}}) is None


def test_tools_list_and_unknown_method():
    tools = m.handle(rpc("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["google_search", "read_page"]
    assert all(t["inputSchema"]["type"] == "object" and t["annotations"]["readOnlyHint"] for t in tools)
    assert m.handle(rpc("resources/list"))["error"]["code"] == -32601
    assert m.handle(rpc("ping"))["result"] == {}


def test_search_argv():
    a = m.build_argv("google_search", {"query": " SK hynix ", "num_results": 5, "news": True, "when": "d", "ai_overview": True})
    assert a == ["-n", "5", "--news", "--when", "d", "--ai", "--", "SK hynix"], a
    assert m.build_argv("google_search", {"query": "--read file:///etc/passwd"})[-2:] == ["--", "--read file:///etc/passwd"]


def test_search_argv_reaches_the_cli_parser_as_a_query():
    """A query that looks like an option must stay a query once orca_search parses it."""
    import orca_search as o
    seen = {}
    o._search = lambda a, slot=0: seen.update(query=a.query, read=a.read, n=a.n) or 0
    o._read = lambda a, slot: seen.update(read_called=True) or 0
    o.close_slot = lambda slot: None
    o.SlotLock = lambda: type("L", (), {"slot": 0, "__enter__": lambda s: s, "__exit__": lambda s, *e: None})()
    assert o.main(m.build_argv("google_search", {"query": "--read http://x", "num_results": 3})) == 0
    assert seen == {"query": "--read http://x", "read": None, "n": 3}, seen


def test_bad_arguments_are_tool_errors_and_never_run_anything():
    bad = [("google_search", {}), ("google_search", {"query": "  "}), ("google_search", {"query": "x", "when": "z"}),
           ("google_search", {"query": "x", "num_results": 0}), ("google_search", {"query": "x", "num_results": True}),
           ("read_page", {"url": "file:///etc/passwd"}), ("read_page", {"url": "javascript:alert(1)"}),
           ("read_page", {"url": "https://a.b", "max_chars": 10}), ("nope", {}), ("read_page", "https://a.b")]
    for name, args in bad:
        run = fake(P("should not run"))
        r = m.call_tool(name, args, run)
        assert r["isError"] and run.calls == [], (name, args, r)


def test_call_runs_the_script_isolated_and_returns_stdout():
    run = fake(P("# Google web: x\n1. Title"))
    r = m.handle(rpc("tools/call", {"name": "google_search", "arguments": {"query": "x"}}), run)["result"]
    assert r == {"content": [{"type": "text", "text": "# Google web: x\n1. Title"}], "isError": False}
    assert run.calls[0][:3] == [sys.executable, "-I", m.SCRIPT] and run.calls[0][3:] == ["-n", "10", "--", "x"]
    run = fake(P("# https://a.b\ntext"))
    m.call_tool("read_page", {"url": "https://a.b"}, run)
    assert run.calls[0][3:] == ["--max-chars", "8000", "--read", "https://a.b"]


def test_failures_carry_the_reason_and_a_fallback():
    r = m.call_tool("google_search", {"query": "x"}, fake(P("", 3, "orca_search: daily cap 40 reached")))
    assert r["isError"] and "daily cap 40 reached" in r["content"][0]["text"] and "WebSearch" in r["content"][0]["text"]
    r = m.call_tool("google_search", {"query": "x"}, fake(P("", 2, "orca_search: orca tab: [Errno 2]")))
    assert r["isError"] and "Orca may not be running" in r["content"][0]["text"]
    r = m.call_tool("read_page", {"url": "https://a.b"}, fake(subprocess.TimeoutExpired("x", 300)))
    assert r["isError"] and "timed out" in r["content"][0]["text"]
    r = m.call_tool("read_page", {"url": "https://a.b"}, fake(OSError("no python")))
    assert r["isError"] and "could not start" in r["content"][0]["text"]


def test_serve_speaks_newline_delimited_json_and_survives_bad_input():
    lines = [rpc("initialize", {"protocolVersion": "2025-06-18"}, 0), {"jsonrpc": "2.0", "method": "notifications/initialized"},
             rpc("tools/list", mid=1), rpc("tools/call", {"name": "google_search", "arguments": {"query": "x"}}, 2)]
    stdin = io.BytesIO(b"\n".join(json.dumps(x).encode() for x in lines) + b"\nnot json\n[1]\n\n")
    stdout = io.BytesIO()
    stdout.close = lambda: None
    m.serve(stdin, stdout, fake(P("results")))
    out = [json.loads(x) for x in stdout.getvalue().decode().splitlines()]
    by_id = {x["id"]: x for x in out}
    assert len(out) == 5 and all(x["jsonrpc"] == "2.0" for x in out), out  # the notification got no reply
    assert by_id[0]["result"]["serverInfo"]["name"] == "orca-search" and len(by_id[1]["result"]["tools"]) == 2
    assert by_id[2]["result"]["content"][0]["text"] == "results"
    assert sorted(x["error"]["code"] for x in out if "error" in x) == [-32700, -32600]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
    print(f"all tests passed ({len(fns)})")
