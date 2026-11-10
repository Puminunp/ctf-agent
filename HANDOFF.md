# HANDOFF (Part 1 to Part 2)

Fill in the `TODO` fields as Part 1 finishes. Part 2 reads this first.

## State of the repo (Nov 9)

- Done and tested: agent loop, tools, limits, trace and result writers, gateway client, controller, generated isolated compose
  environment, solver image, manifest builder, summary script, isolation check. 47 offline tests pass.
- The professor confirmed there is NO instructor kit (compose file, private verifier, helper scripts, shared Linux machine).
  Those were artifacts of writing the guide. Everything above is ours; the README says so.
- Controls evidence exists for `rev-checker` and `pwn-puffin`: `runs/controls/isolation_*.json` (all checks passed).
- Pilot done (Nov 9): `rev-checker`, 1 attempt, solved in 3 steps (read the script, wrote an inverse script, submitted), 7.7 s,
  5,706 in / 926 out tokens, no blocked requests. Local only: `runs/pilot/` is git-ignored and its trace predates the flag-redaction
  fix, so it contains the flag; do not share it. The pilot also found a real bug: the flag showed up in a tool result, so redaction now
  covers the whole trace once a flag is verified (test added).
- Pilot 2 (Nov 9): `rev-beleaf` (Moderate), solved in 10 steps, 49.7 s, 83,636 in / 8,648 out tokens, no blocked requests. The
  redaction fix worked for the full flag, but partial fragments stay visible in earlier steps (see README). Behaviour worth citing:
  steps 5-8 spent about 40% of the tokens fixing an off-by-one in its own objdump-text parsing (it read 31 table entries instead of 33
  and decoded `...re_futurew`); it recovered by checking the length against the section bounds and verified the candidate by running
  the binary ("Correct!") before submitting. Input tokens per call grew 1.4k -> 12.7k because every step re-sends the history.
  Not a failure, so not yet a justified change.
- Implication: two solves out of two give no failure to learn from. Pilot a harder one (`rev-beleaf` Moderate,
  `pwn-puffin` with a target) to find the trace problem worth fixing.
- NOT done: more pilots, the trace-driven change, any scored attempts. `runs/eval/` does not exist yet.
- Open question for the professor (not answered in his reply): whether the grading table's "controlled comparison" still applies.
  Plan that covers both readings: scored baseline = 3 trials x 10 challenges with `config_id = agent`; then re-test one trace-driven fix
  on 2-3 challenges as a separate config (`agent-fix`) in `runs/followup/`, reported separately.

## Fixed configuration

| Item | Value |
|---|---|
| config_id | `agent` |
| Frozen agent commit | TODO (`git rev-parse HEAD`, working tree clean) |
| CTFTiny commit | `f1c9531672c45b24b7fb5f3aa44a7ac33d3602f8` (GitHub `main` on Nov 9; files from the GitHub ZIP) |
| NYU_CTF_Bench commit | not used (cannot be cloned on Windows; development checks use unscored CTFTiny challenges) |
| Model ID and route | `claude-haiku-5-5` via `https://litellm.oit.duke.edu/v1`. Passed `scripts/check_toolcall.py`. Not frozen until the scored run starts. |
| Prompts | `prompts/system.md` (fingerprint recorded per run in `details/`) |
| Limits | `configs/agent.json` (900 s, 60 steps, 400k tokens, 5 wrong flags per attempt) |
| Retry rules | gateway: 2 retries on 429/5xx/connection errors; no attempt-level retries |
| Solver image | `ctf-solver:latest`, built from `docker/solver/Dockerfile` |
| Launch command | README "Run", step 4 |
| Scored challenges | `evaluation_ids.txt` -> `evaluation_manifest.json` (10 challenges, 5 Very Easy, 4 Easy, 1 Moderate; 8 need no target). Chosen from README difficulty labels only; no flags or solutions read. `msc-showdown` was replaced by `rev-unvirtualization` because its target needs `privileged: true` and the Docker socket. |

## Run status

| Item | Value |
|---|---|
| Attempts finished / running / queued (of 30) | TODO |
| Where results are | `runs/eval/results.jsonl`, `runs/eval/traces/`, `runs/eval/details/` |
| Incidents (blocked requests, scope_violation, infrastructure_error, loops) | TODO |
| Tokens and quota used so far | TODO (check the Duke AI dashboard; daily limit unknown) |

## Trace-driven change

| Item | Value |
|---|---|
| Problem observed (run_id, step numbers) | TODO |
| Change made (prompt / tool description / validation / planning / memory) | TODO |
| Follow-up check and result | TODO. Say "proposed" if untested; do not call an untested change "measured". |

## Environment controls evidence (for the report)

| Check | Result |
|---|---|
| Non-root, no sudo, no capabilities, no Docker socket | Passed (`runs/controls/isolation_rev-checker.json`, `isolation_pwn-puffin.json`) |
| Internet, raw IP and host blocked from the solver | Passed (same files) |
| Answer files absent; workspace holds only the listed files | Passed (same files) |
| Target reachable only as `target:<port>` | Passed for `pwn-puffin` |
| Reset between trials clears workspace, volumes and conversation | Design: `down -v` before and after, no bind mounts. TODO: confirm on two consecutive attempts |
| Blocked attempts by the agent during real runs | TODO (read traces for `scope_violation` events) |

## Contribution notes and AI assistance

TODO: who did what. Code was written with Claude Code assistance (disclose per course policy).
