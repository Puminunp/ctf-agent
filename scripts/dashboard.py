#!/usr/bin/env python3
"""Read-only, real-time web dashboard for the Duke AI CTF (Hack The Box event).

Standard library only. Serves a single self-contained page that polls ``/api/state`` every few
seconds. The state combines three read-only sources:

  * local run results   -- runs/race*/<id>/results.jsonl and runs/htb-test/results.jsonl
  * HTB live event data  -- retrieve_ctf / retrieve_ctf_scores over the project's own MCP client
  * spend                -- the LiteLLM gateway key's real spend when reachable, else a token estimate

Nothing here starts, stops, or changes a competition run; it only reads. The HTB token is never
printed or embedded in a response -- the project's McpClient redacts it from its own errors, and
this module never echoes any environment value.

Run:
    python3 scripts/dashboard.py --port 8765      # serve (blocks)
    python3 scripts/dashboard.py --selftest       # build state once, print JSON, exit (no server)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import threading
import time
import traceback
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
HTML_PATH = HERE / "dashboard.html"

CTF_ID = int(os.environ.get("HTB_CTF_ID", "3755"))
OUR_TEAM_ID = 340089
OUR_TEAM_NAME = "[AI] ai-agent-of-jackdebuff"
BUDGET_LIMIT = 25.0
HTB_TTL_S = 15.0          # cache HTB + gateway responses this long so fast polling doesn't hammer them

# Local result dirs that make up the live competition (see task spec).
RESULT_GLOBS = (
    "runs/race/*/results.jsonl",
    "runs/race-deepseek/*/results.jsonl",
    "runs/htb-test/results.jsonl",
    "runs/htb-test/*/results.jsonl",
)
# Dirs scanned for "running" challenges (a run dir that has no results.jsonl yet).
RUNNING_DIRS = ("runs/race", "runs/race-deepseek")

# Card status ranking for sorting / reducing (lower = shown first).
STATUS_RANK = {"solved": 0, "running": 1, "missed": 2, "error": 3, "untried": 4}

# --- shared caches (module level so repeated requests are cheap) -----------------------------------
_lock = threading.Lock()
_htb_cache = {"ts": 0.0, "ev": None, "sc": None, "err": None}
_gw_cache = {"ts": 0.0, "spend": None, "limit": None, "ok": False, "err": None}

# lazy singletons for the project modules / MCP client
_env_loaded = False
_mcp = None
_category_names = None


# ----------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------
def _ensure_env():
    global _env_loaded, _category_names
    if _env_loaded:
        return
    try:
        from ctfagent.envfile import load_env_file
        load_env_file(ROOT / ".env")
    except Exception:
        pass
    try:
        from ctfagent.htb_challenges import CATEGORY_NAMES
        _category_names = CATEGORY_NAMES
    except Exception:
        _category_names = {}
    _env_loaded = True


def category_name(cat_id):
    _ensure_env()
    try:
        return (_category_names or {}).get(int(cat_id), "") or "other"
    except (TypeError, ValueError):
        return "other"


# Canonical display order for the Model Performance panel, grouped by family so the
# Claude / OpenAI / DeepSeek rows cluster together instead of sorting alphabetically.
MODEL_ORDER = (
    "Haiku", "Sonnet", "Opus",                        # Anthropic / Claude
    "GPT-5.3-codex", "GPT-6-sol", "GPT-6-luna", "GPT (open-net)",   # OpenAI / GPT
    "DeepSeek-Pro", "DeepSeek-Flash",                 # DeepSeek
)


def _model_sort_key(m):
    """Sort known labels by MODEL_ORDER (family grouping); unknown labels fall to the end."""
    try:
        return (0, MODEL_ORDER.index(m), "")
    except ValueError:
        return (1, 0, str(m))


def model_for(config_id, run_id=""):
    """Derive a friendly model name from the config/run id (model is not a result field).

    config_ids look like ``agent-htb-<base>-<label>``. Order matters: specific substrings are
    tested before generic ones so ``flash`` beats ``deepseek`` and ``gpt6`` / ``open`` beat ``gpt``.
    """
    s = f"{config_id or ''} {run_id or ''}".lower()
    if "haiku" in s:
        return "Haiku"
    if "sonnet" in s:
        return "Sonnet"
    if "opus" in s:
        return "Opus"
    if "flash" in s:
        return "DeepSeek-Flash"
    if "deepseek" in s:            # deepseek without flash
        return "DeepSeek-Pro"
    if "gpt6" in s:
        return "GPT-6-sol"
    if "open" in s:               # open-net config solved via internet egress
        return "GPT (open-net)"
    if "luna" in s:                # gpt-6-luna config (agent-htb-luna)
        return "GPT-6-luna"
    if "gpt" in s:                 # gpt without gpt6/open/luna
        return "GPT-5.3-codex"
    return str(config_id) if config_id else "unknown"


def card_status(local_status, verified, htb_solved):
    """Collapse a run's raw status + HTB's own solved flag into a single card colour-state."""
    if htb_solved or verified or local_status == "solved":
        return "solved"
    if local_status == "running":
        return "running"
    if local_status in ("no_flag", "scope_violation"):
        return "missed"
    if local_status == "infrastructure_error":
        return "error"
    if local_status:
        return "missed"
    return "untried"


# ----------------------------------------------------------------------------------------------------
# local run results
# ----------------------------------------------------------------------------------------------------
def load_local():
    """Read every competition results row. Returns (rows, running_set).

    rows: list of dicts (parsed JSONL lines, with a derived 'model').
    running_set: {challenge_id(str): model_or_None} for run dirs that exist but have no results yet.
    """
    rows = []
    order = 0
    for pat in RESULT_GLOBS:
        for fp in sorted(glob.glob(str(ROOT / pat))):
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(row, dict):
                            continue
                        row["_order"] = order
                        row["_model"] = model_for(row.get("config_id"), row.get("run_id"))
                        rows.append(row)
                        order += 1
            except OSError:
                continue

    running = {}
    for base in RUNNING_DIRS:
        base_dir = ROOT / base
        if not base_dir.is_dir():
            continue
        fam_model = "DeepSeek" if base.endswith("deepseek") else None
        try:
            for child in base_dir.iterdir():
                if not child.is_dir() or not child.name.isdigit():
                    continue
                if not (child / "results.jsonl").is_file():
                    running.setdefault(child.name, fam_model)
        except OSError:
            continue
    return rows, running


def challenge_runs(rows, running):
    """Group runs per challenge id into per-model 'current' attempts (last row wins per model)."""
    by_cid = defaultdict(lambda: defaultdict(list))   # cid -> model -> [rows]
    for row in rows:
        cid = str(row.get("challenge_id"))
        by_cid[cid][row["_model"]].append(row)

    out = defaultdict(list)   # cid -> [attempt dict]
    for cid, by_model in by_cid.items():
        for model, model_rows in by_model.items():
            model_rows.sort(key=lambda r: r.get("_order", 0))
            cur = model_rows[-1]
            out[cid].append({
                "model": model,
                "status": cur.get("status"),
                "verified": bool(cur.get("verified")),
                "cost_usd": cur.get("cost_usd"),
                "elapsed_s": cur.get("elapsed_s"),
                "input_tokens": cur.get("input_tokens"),
                "output_tokens": cur.get("output_tokens"),
                "trials": len(model_rows),
            })
    for cid, model in running.items():
        # Only add a synthetic running attempt if that model isn't already recorded as finished.
        existing = {a["model"] for a in out[cid]}
        if model in existing:
            continue
        out[cid].append({
            "model": model, "status": "running", "verified": False,
            "cost_usd": None, "elapsed_s": None,
            "input_tokens": None, "output_tokens": None, "trials": 0,
        })
    return out


def pick_primary(attempts):
    """Choose the representative attempt for a challenge's headline model/cost/time."""
    if not attempts:
        return None

    def rank(a):
        st = card_status(a.get("status"), a.get("verified"), False)
        return (STATUS_RANK.get(st, 9), -(a.get("cost_usd") or 0.0), -(a.get("elapsed_s") or 0.0))

    return sorted(attempts, key=rank)[0]


# ----------------------------------------------------------------------------------------------------
# HTB live data (cached ~15s)
# ----------------------------------------------------------------------------------------------------
def _get_mcp():
    global _mcp
    if _mcp is not None:
        return _mcp
    _ensure_env()
    from ctfagent.htb import McpClient, DEFAULT_URL
    token = os.environ.get("HTB_MCP_TOKEN")
    if not token:
        raise RuntimeError("HTB_MCP_TOKEN not set")
    client = McpClient(os.environ.get("HTB_MCP_URL", DEFAULT_URL), token)
    client.connect()
    _mcp = client
    return _mcp


def fetch_htb():
    """Return (ev, sc, err) using a 15s cache; on failure reuse the last cached value."""
    global _mcp
    now = time.time()
    with _lock:
        fresh = (now - _htb_cache["ts"]) < HTB_TTL_S
        have = _htb_cache["ev"] is not None or _htb_cache["sc"] is not None
    if fresh and have:
        return _htb_cache["ev"], _htb_cache["sc"], _htb_cache["err"]

    ev = sc = None
    err = None
    try:
        mcp = _get_mcp()
        ev = mcp.call_tool("retrieve_ctf", {"ctf_id": CTF_ID}, raise_on_tool_error=False)
        sc = mcp.call_tool("retrieve_ctf_scores", {"ctf_id": CTF_ID}, raise_on_tool_error=False)
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
        _mcp = None   # force reconnect next time
    with _lock:
        if ev is not None or sc is not None:
            _htb_cache.update(ts=now, ev=ev, sc=sc, err=None)
            return ev, sc, None
        # failed: keep last good values, note the error
        _htb_cache["ts"] = now
        _htb_cache["err"] = err
        return _htb_cache["ev"], _htb_cache["sc"], err


def fetch_gateway():
    """Real spend from the LiteLLM gateway key (needs Duke VPN). Cached ~15s; None when unreachable."""
    now = time.time()
    with _lock:
        if (now - _gw_cache["ts"]) < HTB_TTL_S and _gw_cache["ts"] > 0:
            return dict(_gw_cache)
    ok, spend, limit, err = False, None, None, None
    try:
        _ensure_env()
        from ctfagent.gateway_budget import key_info
        base = os.environ.get("LITELLM_BASE_URL", "https://litellm.oit.duke.edu/v1")
        token = os.environ.get("LITELLM_TOKEN")
        if token:
            info = key_info(base, token, timeout_s=6.0)
            sp = info.get("spend")
            if sp is not None:
                spend = float(sp)
                mb = info.get("max_budget")
                limit = float(mb) if mb is not None else None
                ok = True
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:120]}"
    with _lock:
        _gw_cache.update(ts=now, spend=spend, limit=limit, ok=ok, err=err)
        return dict(_gw_cache)


# ----------------------------------------------------------------------------------------------------
# build the full state object
# ----------------------------------------------------------------------------------------------------
def build_state():
    """Assemble the /api/state payload. Never raises: on error returns a payload with an 'error' key."""
    now = time.time()
    try:
        rows, running = load_local()
        runs_by_cid = challenge_runs(rows, running)

        # total estimated spend = sum of cost over every loaded result row
        est_spend = sum((r.get("cost_usd") or 0.0) for r in rows)

        ev, sc, htb_err = fetch_htb()

        # ---- challenges (canonical set = HTB's 16; fall back to local ids if HTB is down) ----
        challenges = []
        htb_challenges = (ev or {}).get("challenges") if isinstance(ev, dict) else None
        if htb_challenges:
            for c in htb_challenges:
                cid = str(c.get("id"))
                attempts = runs_by_cid.get(cid, [])
                htb_solved = bool(c.get("solved"))
                primary = pick_primary(attempts)
                p_status = primary.get("status") if primary else None
                p_verified = any(a.get("verified") for a in attempts)
                status = card_status(p_status, p_verified, htb_solved)
                # headline model: the solver if solved locally, else the primary attempt's model
                solver = next((a for a in attempts if a.get("verified")), None)
                head = solver or primary
                challenges.append({
                    "id": c.get("id"),
                    "name": c.get("name") or cid,
                    "difficulty": (c.get("difficulty") or "").lower(),
                    "category": category_name(c.get("challenge_category_id")),
                    "points": c.get("points") or 0,
                    "solved": htb_solved,
                    "status": status,
                    "model": head.get("model") if head else None,
                    "verified": p_verified,
                    "cost_usd": head.get("cost_usd") if head else None,
                    "elapsed_s": head.get("elapsed_s") if head else None,
                    "input_tokens": head.get("input_tokens") if head else None,
                    "output_tokens": head.get("output_tokens") if head else None,
                    "attempts": [
                        {k: a.get(k) for k in ("model", "status", "verified", "cost_usd", "elapsed_s", "trials")}
                        for a in sorted(attempts, key=lambda a: STATUS_RANK.get(
                            card_status(a.get("status"), a.get("verified"), False), 9))
                    ],
                })
        else:
            # HTB unavailable and never cached: show whatever the local runs reveal.
            for cid, attempts in runs_by_cid.items():
                primary = pick_primary(attempts)
                p_verified = any(a.get("verified") for a in attempts)
                status = card_status(primary.get("status") if primary else None, p_verified, False)
                head = next((a for a in attempts if a.get("verified")), None) or primary
                challenges.append({
                    "id": cid, "name": cid, "difficulty": "", "category": "other",
                    "points": 0, "solved": p_verified, "status": status,
                    "model": head.get("model") if head else None, "verified": p_verified,
                    "cost_usd": head.get("cost_usd") if head else None,
                    "elapsed_s": head.get("elapsed_s") if head else None,
                    "input_tokens": head.get("input_tokens") if head else None,
                    "output_tokens": head.get("output_tokens") if head else None,
                    "attempts": attempts,
                })

        # ---- model performance (aggregate over every loaded row) ----
        model_rows = defaultdict(list)
        for r in rows:
            model_rows[r["_model"]].append(r)
        # which challenges each model attempted / solved (distinct)
        model_attempted = defaultdict(set)
        model_solved = defaultdict(set)
        for cid, attempts in runs_by_cid.items():
            for a in attempts:
                m = a.get("model")
                if a.get("status") == "running" and a.get("trials", 0) == 0:
                    model_attempted[m].add(cid)   # count a live run as an attempt
                    continue
                model_attempted[m].add(cid)
                if a.get("verified"):
                    model_solved[m].add(cid)
        models = []
        # List every model that actually has data (>=1 attempt / result row), in family order.
        seen_models = set(model_rows) | set(model_attempted)
        seen_models.discard(None)
        for m in sorted(seen_models, key=_model_sort_key):
            attempts_n = len(model_attempted.get(m, set()))
            solves_n = len(model_solved.get(m, set()))
            spend_m = sum((r.get("cost_usd") or 0.0) for r in model_rows.get(m, []))
            models.append({
                "model": m,
                "attempts": attempts_n,
                "solves": solves_n,
                "spend": round(spend_m, 4),
                "solve_rate": round(solves_n / attempts_n, 3) if attempts_n else 0.0,
            })

        # ---- event / team / totals ----
        ev = ev if isinstance(ev, dict) else {}
        sc = sc if isinstance(sc, dict) else {}
        pteam = ev.get("participating_team") or {}
        steam = sc.get("participating_team") or {}
        event = {
            "name": ev.get("name") or "Duke AI CTF",
            "status": ev.get("status"),
            "ends_at": ev.get("ends_at"),
            "starts_at": ev.get("starts_at"),
        }
        team = {
            "name": pteam.get("name") or OUR_TEAM_NAME,
            "points": pteam.get("points") if pteam.get("points") is not None else steam.get("points"),
            "rank": pteam.get("rank") if pteam.get("rank") is not None else steam.get("position"),
            "solved": pteam.get("solved_challenges")
            if pteam.get("solved_challenges") is not None else steam.get("solved_challenges"),
            "total": pteam.get("total_challenges")
            if pteam.get("total_challenges") is not None else steam.get("total_challenges"),
            "first_bloods": steam.get("first_bloods"),
        }
        totals = {"teams": sc.get("ctf_teams"), "players": sc.get("ctf_players")}

        # ---- scoreboard (already ranked; position field is often null -> use index) ----
        scoreboard = []
        for i, s in enumerate(sc.get("scores") or []):
            pos = s.get("position")
            if pos is None:
                pos = i + 1
            is_us = (s.get("id") == OUR_TEAM_ID) or (s.get("name") == OUR_TEAM_NAME)
            scoreboard.append({
                "name": s.get("name"),
                "points": s.get("points") or 0,
                "position": pos,
                "first_bloods": s.get("first_bloods"),
                "is_us": is_us,
            })

        # ---- spend ----
        gw = fetch_gateway()
        if gw.get("ok") and gw.get("spend") is not None:
            spend = {
                "used": round(float(gw["spend"]), 4),
                "limit": float(gw["limit"]) if gw.get("limit") else BUDGET_LIMIT,
                "source": "real",
            }
        else:
            spend = {"used": round(est_spend, 4), "limit": BUDGET_LIMIT, "source": "estimate"}

        state = {
            "updated_at": now,
            "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "event": event,
            "team": team,
            "totals": totals,
            "spend": spend,
            "challenges": challenges,
            "models": models,
            "scoreboard": scoreboard,
        }
        if htb_err:
            state["htb_warning"] = htb_err
        return state
    except Exception as e:
        return {
            "error": f"{type(e).__name__}: {str(e)[:300]}",
            "trace": traceback.format_exc()[-800:],
            "updated_at": now,
            "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }


# ----------------------------------------------------------------------------------------------------
# HTTP server
# ----------------------------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "CTFDash/1.0"

    def log_message(self, *args):   # keep the console quiet
        pass

    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                try:
                    html = HTML_PATH.read_text(encoding="utf-8")
                    self._send(200, html, "text/html; charset=utf-8")
                except OSError as e:
                    self._send(200, f"<h1>dashboard.html not found</h1><pre>{e}</pre>",
                               "text/html; charset=utf-8")
            elif path == "/api/state":
                state = build_state()
                self._send(200, json.dumps(state), "application/json; charset=utf-8")
            elif path == "/healthz":
                self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            else:
                self._send(404, json.dumps({"error": "not found"}), "application/json; charset=utf-8")
        except Exception as e:
            # Never crash the server: always answer with HTTP 200 so the page keeps polling.
            self._send(200, json.dumps({"error": f"{type(e).__name__}: {str(e)[:200]}",
                                        "updated_at": time.time()}),
                       "application/json; charset=utf-8")


def main():
    ap = argparse.ArgumentParser(description="Read-only Duke AI CTF live dashboard")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--selftest", action="store_true",
                    help="build state once, print it as JSON, and exit (no server)")
    args = ap.parse_args()

    if args.selftest:
        print(json.dumps(build_state(), indent=2, default=str))
        return

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CTF dashboard on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
