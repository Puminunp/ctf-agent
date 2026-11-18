"""Hack The Box challenges for the live competition, on top of the trusted controller.

Where CTFTiny ships a flag and a local target, an HTB challenge is remote: the catalog reads the event
over the MCP server, starts the challenge container (a public host:port), downloads any files, and checks
flags by submitting them to HTB. The flag is never known locally.

The solver still runs in the same hardened sandbox; `render_remote_compose` gives it a route to the one
challenge host and nothing else (see environment.py).
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .challenges import Task, host_file_paths, task_prompt
from .controller import Controller, Prepared
from .htb import HtbError, McpClient
from .trace import Trace
from .verifier import VerifierUnavailable

# HTB CTF category ids. 2 = Web is confirmed from the Duke event's test challenge; the rest follow HTB's
# usual ordering and are refined as the real challenges appear. An unknown id falls back to "".
CATEGORY_NAMES = {1: "reversing", 2: "web", 3: "pwn", 4: "crypto", 5: "forensics",
                  6: "misc", 7: "osint", 8: "hardware", 9: "blockchain", 10: "mobile"}

# Words in HTB's submit_flag reply that settle a submission either way.
_CORRECT_WORDS = ("correct", "congrat", "solved", "accepted", "well done", "first blood")
_WRONG_WORDS = ("incorrect", "wrong", "invalid", "not correct", "try again", "already")
_RETRY_STATUS = {425, 429, 500, 502, 503, 504}


@dataclass
class HtbChallenge:
    """The runtime object for one HTB challenge. Shaped so environment.py and challenges.py can read it."""
    challenge_id: int
    name: str
    category: str
    description: str
    difficulty: str
    points: int
    files: list[str] = field(default_factory=list)
    challenge_dir: Path | None = None
    is_remote: bool = True
    remote_host: str | None = None
    remote_ports: list[int] = field(default_factory=list)
    flag: None = None            # never known locally; HTB checks it


def classify_submission(result) -> bool:
    """True/False from HTB's submit_flag reply. Raises VerifierUnavailable when it cannot be judged."""
    if isinstance(result, dict):
        status = result.get("status_code")
        if isinstance(status, int) and status in _RETRY_STATUS:
            raise VerifierUnavailable(f"HTB submit returned {status}")
        for key in ("correct", "is_correct", "success", "solved", "isCorrect"):
            if isinstance(result.get(key), bool):
                return result[key]
        text = " ".join(str(result.get(k, "")) for k in ("message", "status", "detail", "error", "result")).lower()
    else:
        text = str(result or "").lower()
    if any(w in text for w in _WRONG_WORDS):
        return False
    if any(w in text for w in _CORRECT_WORDS):
        return True
    raise VerifierUnavailable(f"could not read HTB's submit reply: {str(result)[:200]}")


class HtbVerifier:
    """Checks a flag by submitting it to HTB. A real wrong answer is False; a transport or rate-limit
    problem raises VerifierUnavailable so the attempt loop retries instead of scoring it wrong."""

    def __init__(self, mcp: McpClient, challenge_id: int):
        self.mcp = mcp
        self.challenge_id = challenge_id
        self.last_result = None

    def verify(self, candidate: str) -> bool:
        try:
            result = self.mcp.call_tool("submit_flag",
                                        {"challenge_id": self.challenge_id, "flag": candidate},
                                        raise_on_tool_error=False)
        except HtbError as e:
            raise VerifierUnavailable(str(e)) from None
        self.last_result = result
        return classify_submission(result)


class HtbCatalog:
    """Reads an HTB event and drives challenge containers over the MCP server."""

    def __init__(self, mcp: McpClient, ctf_id: int, files_root: str | Path,
                 start_timeout_s: float = 120.0, poll_s: float = 4.0, sleep=time.sleep,
                 start_retries: int = 3):
        self.mcp = mcp
        self.ctf_id = ctf_id
        self.files_root = Path(files_root)
        self.start_timeout_s = start_timeout_s
        self.poll_s = poll_s
        self._sleep = sleep
        self.start_retries = start_retries

    def challenges(self) -> list[dict]:
        ctf = self.mcp.call_tool("retrieve_ctf", {"ctf_id": self.ctf_id})
        if not isinstance(ctf, dict) or "challenges" not in ctf:
            raise HtbError(f"event {self.ctf_id} returned no challenge list")
        return ctf["challenges"]

    def find(self, challenge_id: int) -> dict:
        for c in self.challenges():
            if c.get("id") == challenge_id:
                return c
        raise HtbError(f"challenge {challenge_id} is not in event {self.ctf_id}")

    def start(self, challenge_id: int) -> tuple[str | None, list[int]]:
        """Start the container (if the challenge has one) and wait until it reports a host and ports.

        A container already running from an earlier call is fine: HTB refuses the second start, and we
        just poll for its address. A *transient* start error (a 5xx / "Server Error", which HTB returns
        intermittently) is retried a few times before giving up, so one HTB blip does not kill a
        challenge outright during the event.
        """
        for attempt in range(self.start_retries + 1):
            try:
                res = self.mcp.call_tool("start_container", {"challenge_id": challenge_id},
                                         raise_on_tool_error=False)
            except HtbError:                                   # transport failure: retry, then re-raise
                if attempt < self.start_retries:
                    self._sleep(self.poll_s)
                    continue
                raise
            err = res.get("error") if isinstance(res, dict) else None
            if not err or "already" in str(err).lower():       # started, or already running -> go poll
                break
            status = res.get("status_code") if isinstance(res, dict) else None
            transient = status in _RETRY_STATUS or "server error" in str(err).lower() \
                or "unavailable" in str(err).lower()
            if transient and attempt < self.start_retries:
                self._sleep(self.poll_s)
                continue
            raise HtbError(f"start_container refused: {err}")
        deadline = time.monotonic() + self.start_timeout_s
        last = None
        while time.monotonic() < deadline:
            self._sleep(self.poll_s)
            try:
                status = self.mcp.call_tool("container_status", {"challenge_id": challenge_id})
            except HtbError as e:
                last = str(e)
                continue
            if isinstance(status, dict):
                host = status.get("hostname") or status.get("host") or status.get("ip")
                ports = status.get("ports") or status.get("docker_ports") or []
                ready = status.get("status") in (None, "ready", "running", "online") or host
                if host and ports and ready:
                    return str(host), [int(p) for p in ports]
                last = str(status)
        raise HtbError(f"container for {challenge_id} did not become ready in {self.start_timeout_s:.0f}s "
                       f"(last status: {last})")

    def stop(self, challenge_id: int) -> None:
        try:
            self.mcp.call_tool("stop_container", {"challenge_id": challenge_id})
        except HtbError:
            pass

    def download_files(self, challenge_id: int, filename: str) -> tuple[Path | None, list[str]]:
        """Fetch the challenge's downloadable bundle (when it has one) into its own directory."""
        if not filename:
            return None, []
        link = self.mcp.call_tool("get_download_link", {"challenge_id": challenge_id})
        url = link.get("url") if isinstance(link, dict) else link
        if not url:
            return None, []
        dest = self.files_root / str(challenge_id)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / filename
        req = urllib.request.Request(url, headers={"User-Agent": "ctf-agent"})
        with urllib.request.urlopen(req, timeout=60) as resp, out.open("wb") as fh:
            fh.write(resp.read())
        return dest, [filename]


class HtbController(Controller):
    """Controller whose target is an HTB event. Overrides only how an attempt is set up and torn down."""

    def __init__(self, *args, catalog: HtbCatalog, mcp: McpClient, **kwargs):
        super().__init__(*args, **kwargs)
        self.catalog = catalog
        self.mcp = mcp
        self._live: int | None = None

    def prepare(self, challenge_id: str, trace: Trace, detail: dict) -> Prepared:
        t0 = time.monotonic()
        cid = int(challenge_id)
        info = self.catalog.find(cid)
        name = str(info.get("name") or challenge_id)
        category = CATEGORY_NAMES.get(info.get("challenge_category_id"), "")
        difficulty = str(info.get("difficulty") or "")
        points = int(info.get("points") or 0)
        detail.update(challenge_name=name, category=category, difficulty=difficulty, points=points)

        host, ports = None, []
        if info.get("hasDocker"):
            host, ports = self.catalog.start(cid)
            self._live = cid
        challenge_dir, files = self.catalog.download_files(cid, str(info.get("filename") or ""))

        chal = HtbChallenge(challenge_id=cid, name=name, category=category,
                            description=str(info.get("description") or ""), difficulty=difficulty,
                            points=points, files=files, challenge_dir=challenge_dir,
                            is_remote=True, remote_host=host, remote_ports=ports)

        target_host = self.cfg.environment.target_host if host else None
        task = Task(challenge_id=challenge_id, name=name, category=category,
                    description=str(info.get("description") or ""), files=files,
                    target_host=target_host, target_port=(ports[0] if ports else None),
                    allowed_hosts={target_host} if target_host else set())

        reset_id = self.env.reset(challenge_id, chal)
        paths = host_file_paths(chal) if files else []
        inventory = self.env.export(paths, self.cfg.environment.workdir)
        verifier = HtbVerifier(self.mcp, cid)

        detail["reset_s"] = round(time.monotonic() - t0, 3)
        detail["export_inventory"] = inventory
        detail["target"] = {"host": host, "ports": ports}
        trace.event("environment_ready", reset_id=reset_id, files=inventory,
                    challenge=name, category=category, difficulty=difficulty, target_ports=ports)
        return Prepared(reset_id, verifier, task_prompt(task, self.cfg.environment.workdir), task.allowed_hosts)

    def cleanup(self, challenge_id: str, detail: dict) -> None:
        if self._live is not None:
            self.catalog.stop(self._live)
            self._live = None
        self.env.stop()
