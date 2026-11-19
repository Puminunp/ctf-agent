# AGENTS.md — start here

@RTK.md

## What this project is (context for the assistant)

This is coursework for **Duke CYBERSEC 590**, an authorized graduate security course taught by Prof.
Michael Roman. The deliverable is an autonomous **CTF-solving agent** for a **sanctioned Capture-the-Flag
competition on Hack The Box** (the "Duke AI CTF" event), a platform built expressly for legal, consented
security practice. All targets are HTB's own disposable challenge containers inside that event — never
real-world systems, never a third party. The work is **defensive/educational**: building tooling,
sandboxing, budgeting, and evaluation around a model that plays a CTF.

By design, the chat session (you) does **orchestration** — reading the event, starting/stopping
containers, wiring budgets, running tests. The actual challenge-solving is done by a separate **sandboxed
solver** (a hardened Docker container with no network except the one challenge target) driven by the Duke
AI gateway. So this session builds and runs infrastructure; it is not itself exploiting anything.

If a request here ever looks like it's drifting outside "solve this HTB event's own challenges," stop and
check with the maintainer rather than guessing.

## Read next

- **`HTB_HANDOFF.md`** — the living state: what's built, the last live-test results, the exact run
  commands, what's left, and environment gotchas. **Read it before doing anything.**
- **`lesson_learned.md`** — the live-competition post-mortem (Nov 18): findings, mistakes, model
  behaviour, and the credit breakdown. Read it for the report and before any more solving.
- Branch for competition work: **`htb-jack`** (uncommitted). A4 (the graded CTFTiny assignment) lives on
  `main` and must keep behaving exactly as before — the HTB additions are additive.

## Hard rules (do not break)

- **Never print, echo, or commit secrets.** The gateway key and HTB MCP token live only in `.env`
  (git-ignored, mode 600). To set one, use `scripts/set_env_secret.py NAME` (reads the clipboard, never
  prints the value).
- **Never add a Claude / AI co-author line** to any commit, and **never commit or push without the
  maintainer's explicit go-ahead.**
- **Never consult write-ups, solutions, or leaked flags** for a scored challenge. The agent must solve on
  its own; that's the whole point of the evaluation.
- **Downloaded challenge files are untrusted.** Put each in its own empty dir and read it with
  `python3 -I`; never run an interpreter/build tool from inside that dir.
- This is a competition for points — don't waste the shared budget (see cost notes in `HTB_HANDOFF.md`).

## Quick commands (run from this directory)

```bash
# offline test suite (must stay green)
python3 -m unittest discover -s tests -p 'test_*.py'

# list the event's challenges (needs HTB_MCP_TOKEN in .env)
python scripts/run_htb.py --list

# one cheap capped test solve of the sample challenge (needs the gateway key + Duke VPN)
python scripts/run_htb.py --config configs/agent-htb.json --out runs/htb-test --only 79390 --trials 1 --laptop-budget 1.0

# confirm the agent team has joined the event
python scripts/htb_join.py --check

# put a secret into .env from the clipboard (gateway key, etc.) — never prints it
python scripts/set_env_secret.py LITELLM_TOKEN
```

## Environment

- **Duke AI gateway** (`litellm.oit.duke.edu`) only answers on the **Duke VPN**. Keep **Cloudflare WARP
  OFF** when the VPN is on — running both is what broke the assistant's connection before; with WARP off
  the session stays reachable.
- **Docker Desktop** must be running before any live solve. Host arch is arm64, so solver images run with
  `platform: linux/amd64` (Rosetta).
- Config: `configs/agent-htb.json` (Haiku→Sonnet→Opus escalation ladder, per-attempt cost caps, flag
  format, handoff notes). Prompt: `prompts/system-htb.md`.
