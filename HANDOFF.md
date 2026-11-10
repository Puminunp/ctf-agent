# HANDOFF (Part 1 to Part 2)

Fill in the blanks marked `TODO` as Part 1 finishes. Part 2 reads this first.

## State of the repo

- Agent loop, tools, limits, trace and result writers, gateway client, controller: **done, 31 offline tests pass.**
- NOT done and NOT run: anything against a live model, a live target, the instructor's compose file, or the real `nyuctf` package.
  See "Adaptation points" in README.md.
- No scored attempts exist yet. `runs/eval/` is empty.

## Fixed configuration

| Item | Value |
|---|---|
| config_id | `agent` |
| Frozen agent commit | TODO (`git rev-parse HEAD`, working tree clean) |
| NYU_CTF_Bench commit | TODO |
| CTFTiny commit | `f1c9531672c45b24b7fb5f3aa44a7ac33d3602f8` (equals GitHub `main` on Nov 9; files came from the GitHub ZIP, see below) |
| Model ID and route | `claude-haiku-5-5` via `https://litellm.oit.duke.edu/v1` (working default; passed `scripts/check_toolcall.py` on Nov 9: input 820+894, output 55+37 tokens). Not frozen until the scored run starts. |
| Prompts | `prompts/system.md` (fingerprint recorded per run in `details/`) |
| Limits | `configs/agent.json` |
| Retry rules | gateway: 2 retries on 429/5xx/connection errors; no attempt-level retries |
| Launch command | see README "Launch" |
| Scored challenges | `evaluation_ids.txt` holds a SUGGESTED 10 (5 Very Easy, 4 Easy, 1 Moderate; 7 need no service). Chosen from the CTFTiny README difficulty labels only; no flags or solutions were read. Edit it if the team prefers other IDs. `evaluation_manifest.json` is still TODO. |

## Run status

| Item | Value |
|---|---|
| Attempts finished / running / queued (of 3 x N) | TODO |
| Where results are | `runs/eval/results.jsonl`, `runs/eval/traces/`, `runs/eval/details/` |
| Incidents (blocked requests, scope_violation, infrastructure_error, loops) | TODO |
| Tokens and quota used so far | TODO |

## Trace-driven change

| Item | Value |
|---|---|
| Problem observed (run_id, step numbers) | TODO |
| Change made (prompt / tool description / validation / planning / memory) | TODO |
| Follow-up check on development challenges and result | TODO |
| Status | TODO: tested, or proposed only. Do not call an untested change "measured". |

## Environment controls evidence (for the report)

| Check | Result |
|---|---|
| `docker compose config --networks` reviewed | TODO |
| Host and internet unreachable from solver (blocked request logged) | TODO |
| No Docker socket, no sudo, no published ports | TODO |
| Reset clears workspace, volumes and conversation between trials | TODO |

## Contribution notes and AI assistance

TODO: who did what. Code was written with Claude Code assistance (disclose per course policy).
