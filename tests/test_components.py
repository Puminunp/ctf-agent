import http.server
import json
import threading
import unittest

from helpers import make_cfg  # noqa: F401  (also puts the repo on sys.path)
from ctfagent.challenges import sanitize_description
from ctfagent.config import Limits
from ctfagent.llm import GatewayClient, LLMError, parse_response
from ctfagent.scope import find_violations
from ctfagent.tools import check_call
from ctfagent.trace import Trace

LIM = Limits(tool_timeout_s=30, max_output_chars=500)


class Scope(unittest.TestCase):
    def test_blocks_foreign_url_and_ip(self):
        self.assertEqual(find_violations("curl https://ctf.example.org/x", {"target"}), ["ctf.example.org"])
        self.assertEqual(find_violations("nc 8.8.8.8 53", {"target"}), ["8.8.8.8"])
        self.assertEqual(find_violations("python -c \"remote('evil.example', 1)\"", {"target"}), ["evil.example"])

    def test_allows_target_loopback_and_plain_commands(self):
        for cmd in ["curl http://target:1337/a", "nc target 1337", "curl http://127.0.0.1/", "ls -la; echo 1.2.3.4",
                    "strings a.out | grep flag", "curl http://$HOST/x"]:
            self.assertEqual(find_violations(cmd, {"target"}), [], cmd)


class Tools(unittest.TestCase):
    def test_validation_messages(self):
        self.assertIn("unknown tool", check_call("rm", "{}", LIM, "/workspace").error)
        self.assertIn("valid JSON", check_call("run_shell", "{", LIM, "/workspace").error)
        self.assertIn("non-empty", check_call("run_shell", '{"command": ""}', LIM, "/workspace").error)
        self.assertIn("4000", check_call("run_shell", json.dumps({"command": "a" * 4001}), LIM, "/workspace").error)
        self.assertIn("one line", check_call("submit_flag", json.dumps({"flag": "a\nb"}), LIM, "/workspace").error)

    def test_read_file_stays_inside_workdir(self):
        self.assertIsNone(check_call("read_file", '{"path": "a.txt"}', LIM, "/workspace").error)
        self.assertEqual(check_call("read_file", '{"path": "a.txt"}', LIM, "/workspace").args["path"], "/workspace/a.txt")
        for bad in ["/etc/passwd", "../etc/passwd", "/workspace/../etc/passwd"]:
            self.assertIn("inside", check_call("read_file", json.dumps({"path": bad}), LIM, "/workspace").error)

    def test_timeout_capped(self):
        self.assertEqual(check_call("run_shell", '{"command":"x","timeout_s":999}', LIM, "/w").args["timeout_s"], 30)


class TraceRedaction(unittest.TestCase):
    def test_secret_is_redacted_everywhere(self):
        t = Trace(None, secrets=["sk-secret-token-123"])
        t.event("x", a="Bearer sk-secret-token-123", nested={"b": ["sk-secret-token-123"]})
        self.assertNotIn("sk-secret-token-123", json.dumps(t.events))


class Description(unittest.TestCase):
    def test_original_hosts_rewritten(self):
        out = sanitize_description("Connect to pwn.chal.csaw.io 8000 or {box}:{port}", "target", 8000)
        self.assertEqual(out, "Connect to target 8000 or target:8000")


class TaskBuilding(unittest.TestCase):
    def test_original_box_name_never_reaches_solver(self):
        from types import SimpleNamespace
        from ctfagent.challenges import build_task
        chal = SimpleNamespace(name="n", category="pwn", files=[], server_name="puffin-box", port=1337,
                               description="Connect to puffin-box 1337.")
        t = build_task("pwn-x", chal, "target")
        self.assertNotIn("puffin-box", t.description)
        self.assertEqual((t.target_host, t.target_port, t.allowed_hosts), ("target", 1337, {"target"}))


class Gateway(unittest.TestCase):
    def test_parse_response_and_missing_usage(self):
        payload = {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "run_shell", "arguments": "{\"command\":\"ls\"}"}}]},
            "finish_reason": "tool_calls"}]}
        r = parse_response(payload, 0.5)
        self.assertEqual((r.tool_calls[0].name, r.input_tokens), ("run_shell", None))
        with self.assertRaises(LLMError):
            parse_response({}, 0)

    def _serve(self, statuses):
        calls = {"n": 0, "auth": None}
        body = json.dumps({"choices": [{"message": {"content": "hi"}}],
                           "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                calls["auth"] = self.headers.get("Authorization")
                self.rfile.read(int(self.headers["Content-Length"]))
                code = statuses[min(calls["n"], len(statuses) - 1)]
                calls["n"] += 1
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body if code == 200 else b"{}")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}/v1", calls

    def test_retries_then_succeeds_and_sends_token(self):
        url, calls = self._serve([503, 200])
        c = GatewayClient(url, "tok-abc", "m", retries=2, sleep=lambda s: None)
        r = c.complete([{"role": "user", "content": "x"}], [])
        self.assertEqual((r.input_tokens, r.output_tokens, calls["n"], calls["auth"]), (7, 3, 2, "Bearer tok-abc"))

    def _serve_429(self, retry_after=None, fail_times=3):
        calls = {"n": 0}
        ok = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                calls["n"] += 1
                if calls["n"] <= fail_times:
                    self.send_response(429)
                    if retry_after:
                        self.send_header("Retry-After", retry_after)
                    self.end_headers()
                    self.wfile.write(b"{}")
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(ok)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}/v1", calls

    def test_baseline_gives_up_after_two_retries_on_repeated_429(self):
        url, calls = self._serve_429(fail_times=3)
        waits = []
        c = GatewayClient(url, "t", "m", retries=2, sleep=waits.append)
        with self.assertRaises(LLMError) as cm:
            c.complete([], [])
        self.assertIn("429", str(cm.exception))
        self.assertEqual((calls["n"], waits), (3, [1, 2]))

    def test_fix_survives_repeated_429_and_honors_retry_after(self):
        url, calls = self._serve_429(retry_after="20", fail_times=3)
        waits = []
        c = GatewayClient(url, "t", "m", retries=6, sleep=waits.append, backoff_cap_s=60,
                          honor_retry_after=True, retry_budget_s=150)
        r = c.complete([], [])
        self.assertEqual((r.content, calls["n"]), ("hi", 4))
        self.assertEqual(waits, [20, 20, 20])

    def test_retry_budget_stops_waiting(self):
        url, calls = self._serve_429(retry_after="50", fail_times=99)
        waits = []
        c = GatewayClient(url, "t", "m", retries=6, sleep=waits.append, backoff_cap_s=60,
                          honor_retry_after=True, retry_budget_s=120)
        with self.assertRaises(LLMError):
            c.complete([], [])
        self.assertLessEqual(sum(waits), 120)
        self.assertEqual(waits, [50, 50])

    def test_error_message_never_contains_token(self):
        url, _ = self._serve([401])
        c = GatewayClient(url, "tok-abc", "m", retries=2, sleep=lambda s: None)
        with self.assertRaises(LLMError) as cm:
            c.complete([], [])
        self.assertNotIn("tok-abc", str(cm.exception))
        self.assertIn("401", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
