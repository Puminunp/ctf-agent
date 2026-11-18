"""Hack The Box CTF access for the trusted controller, through HTB's MCP server.

Standard library only. The MCP token stays in this process: it is sent as a bearer header and never
appears in an exception, a log line, a trace or anything the model sees.

The server speaks the MCP "Streamable HTTP" transport: JSON-RPC over POST, answered either as plain
JSON or as a short server-sent-event stream.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.hackthebox.ai/v1/ctf/mcp/"


class HtbError(Exception):
    """HTB could not be reached, refused the request, or answered with something unusable."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def parse_body(content_type: str, raw: str) -> dict | None:
    """Return the JSON-RPC message from a plain JSON body or from the last data line of an SSE body."""
    if "text/event-stream" in (content_type or ""):
        message = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    message = json.loads(line[5:].strip())
                except ValueError:
                    continue
        return message
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise HtbError("HTB returned a body that is not JSON") from None


def unwrap_tool_result(result: dict):
    """Turn an MCP tools/call result into plain data (dict, list or text)."""
    structured = result.get("structuredContent")
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    parts = []
    for item in result.get("content") or []:
        if item.get("type") != "text":
            continue
        try:
            parts.append(json.loads(item["text"]))
        except ValueError:
            parts.append(item["text"])
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else parts


class McpClient:
    PROTOCOL = "2025-03-26"
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, url: str, token: str, timeout_s: float = 60.0, retries: int = 3, sleep=time.sleep,
                 opener=urllib.request.urlopen):
        if not url or not token:
            raise HtbError("the HTB MCP URL and token are both required (see .env)")
        self.url = url
        self._token = token
        self.timeout_s = timeout_s
        self.retries = retries
        self._sleep = sleep
        self._open = opener
        self._session: str | None = None
        self._next_id = 0
        self._ready = False

    def _clean(self, text: str) -> str:
        return text.replace(self._token, "[REDACTED]")

    def _post(self, body: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Authorization": f"Bearer {self._token}", "User-Agent": "ctf-agent"}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        data = json.dumps(body).encode()
        problem, status = "unknown", None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
                with self._open(req, timeout=self.timeout_s) as resp:
                    self._session = resp.headers.get("Mcp-Session-Id") or self._session
                    return parse_body(resp.headers.get("Content-Type", ""), resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                status = e.code
                problem = f"HTTP {e.code}"
                if e.code not in self.RETRY_STATUS:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                status, problem = None, f"connection problem ({type(e).__name__})"
            if attempt < self.retries:
                self._sleep(min(2 ** attempt, 8))
        raise HtbError(f"HTB MCP call failed: {problem}", status)

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}})
        if not isinstance(msg, dict):
            raise HtbError(f"HTB MCP gave no answer to {method}")
        if msg.get("error"):
            err = msg["error"]
            raise HtbError(self._clean(f"HTB MCP error on {method}: {err.get('message', err)}"))
        return msg.get("result") or {}

    def connect(self) -> dict:
        """Open the MCP session. Returns the server info (name, version)."""
        self._session, self._ready = None, False
        result = self._request("initialize", {"protocolVersion": self.PROTOCOL, "capabilities": {},
                                              "clientInfo": {"name": "ctf-agent", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True
        return result.get("serverInfo") or {}

    def list_tools(self) -> list[dict]:
        if not self._ready:
            self.connect()
        return self._request("tools/list").get("tools") or []

    def call_tool(self, name: str, arguments: dict | None = None, raise_on_tool_error: bool = True):
        """Call one HTB tool and return its data. A lost session is reopened once.

        With raise_on_tool_error=False the tool's own error payload is returned instead of raised, so a
        caller (the flag verifier) can tell a wrong answer from a transport failure. Transport and
        JSON-RPC errors still raise either way.
        """
        if not self._ready:
            self.connect()
        params = {"name": name, "arguments": arguments or {}}
        try:
            result = self._request("tools/call", params)
        except HtbError as e:
            if e.status not in (400, 404):
                raise
            self.connect()
            result = self._request("tools/call", params)
        data = unwrap_tool_result(result)
        if not raise_on_tool_error:
            return data
        if result.get("isError"):
            raise HtbError(self._clean(f"HTB tool {name} failed: {str(data)[:300]}"))
        if isinstance(data, dict) and data.get("error") and data.get("status_code"):
            raise HtbError(self._clean(f"HTB tool {name} refused: {str(data['error'])[:300]}"),
                           int(data["status_code"]))
        return data
