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
- Pilot 3 (Nov 9): `rev-tablez` (Moderate), solved in 5 steps, 11.5 s, 18,676 in / 1,525 out tokens. Inverted a 255-entry translation
  table in one script; submitted without running the binary to confirm (it was right).
- Pilot 4 (Nov 9): `pwn-puffin` (Very Easy, live target), solved in 4 steps, 13.0 s, 11,161 in / 1,003 out tokens. First run through the internal
  network: the agent reached `target:31140` with `nc`, overflowed the buffer, got the flag. Reset took 3.2 s.
- Scored baseline DONE (Nov 10, tag `frozen-eval-v1`): 24 of 30 solved, 6 HTTP 429 gateway errors (see "Run status"). Re-run of those 6 slots
  under `agent-fix`: 6 of 6 solved (`runs/rerun/`). Both are summarised below.
- **Professor's update (Nov 10).** The revised guide drops the instructor infrastructure: use the CTFTiny repo's files, verify flags locally
  from benchmark metadata (kept away from the agent), helper scripts are optional, we choose our own challenge IDs, start with a Very Easy
  challenge. All of this matches what was built. The assignment text the professor re-posted is the ORIGINAL rubric, so it applies:
  a controlled comparison of two configurations (20 pts), pass@1/2/3, average solve rate and variance, time/calls/tokens/cost, solve-rate
  change in percentage points with trace citations, a failure analysis, and a video or demo of a SUCCESSFUL autonomous run (3 pts).
  Hints: a smaller tool-capable model while debugging (we use `claude-haiku-5-5`); connect to Duke VPN before the AI Gateway.
- **UPDATE Nov 10 night: the full `agent-fix` run is DONE (third launch, Duke VPN connected): 30 of 30 solved, 0 infrastructure errors**, recorded at
  commit `2619f77` (no attempt flagged dirty), output `runs/fix/` (+ `summary.json`, `per_challenge.csv`). Comparison with the baseline
  (`runs/comparison.md` / `.json`): success 80.0% -> 100.0% (+20.0 pp), pass@1/2/3 70/90/100 -> 100/100/100, solve rate by trial 70/80/90 -> 100/100/100,
  mean 80.0 -> 100.0, variance 100.0 -> 0.0 pp^2, wall-clock 1,261.5 -> 1,819.6 s (+44%), model calls 201 -> 225, tokens 1.34M -> 1.55M (+214k, +16%),
  estimated cost $0.197 -> $0.235. Plots are in `runs/plots/` (4 PNGs). `REPORT_DRAFT.md` section 5 is updated with the full comparison; the 6-slot
  re-run below is now just an earlier check. The selected configuration for the final is `agent-fix`. Both configs are at the ceiling on these 10
  challenges, so the comparison measures robustness to rate limits, not skill. Remaining: video of a fresh successful run, contribution statements,
  trim the report to about 3 pages, clean-clone README check, submit. The text below about the run being impossible is HISTORY.
- (History) Earlier on Nov 10: the full `agent-fix` run could not be completed. Launch 1 failed in 0.3 s per attempt because Docker Desktop's
  engine had stopped (30 infrastructure errors, no tokens; kept in `runs/fix_aborted_docker_down/`). Launch 2 failed after ~3.5 min per attempt because
  the Duke AI Gateway became unreachable from this PC (needs Duke VPN or campus network; the owner cannot use the VPN); stopped after 7 records
  (`runs/fix_aborted_network_down/`). Nothing was lost; both are harness failures, not results. Fallback comparison: baseline vs `agent-fix` on the
  SAME 6 slots (`scripts/compare_rerun.py` -> `runs/rerun/comparison.json`): 0/6 -> 6/6 (+100 pp), +634.5 s, +571,402 tokens, +38 model/tool calls, +$0.082
  (the baseline attempts stopped early). A first full report draft is in `REPORT_DRAFT.md`. If the gateway becomes reachable (campus Wi-Fi or VPN),
  the full run is one command (below) and the draft's section 5 should then use it.
- The full comparison, if it can be run: baseline `agent` (30 attempts,
  `runs/eval/`) vs `agent-fix` run fresh on all 10 challenges x 3 trials (`runs/fix/`, NOT RUN). Then run
  `scripts/compare_configs.py --manifest evaluation_manifest.json --a runs/eval --b runs/fix --out runs/comparison.json --md runs/comparison.md`.
  The baseline's own metrics are already in `runs/baseline_metrics.md` / `.json`.
- Baseline metrics (config `agent`, all attempts counted, infrastructure errors counted as failures): success 80.0%; pass@1 70.0, pass@2 90.0,
  pass@3 100.0; solve rate by trial 70 / 80 / 90, mean 80.0, sample variance 100.0 pp^2; excluding infra errors the success rate is 100.0%.
  201 model calls, 202 tool calls, 1,261.5 s total (42.1 s per attempt), 1,177,441 in / 159,101 out tokens, estimated cost $0.197.
- Cost is an ESTIMATE at Anthropic list prices for `claude-haiku-5-5` ($0.10 in / $0.50 out per million tokens, prompts under 100K tokens,
  no caching). The Duke gateway may bill differently; say so in the report.

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
| Scored challenges | `evaluation_ids.txt` -> `evaluation_manifest.json`: `cry-hybrid2`, `rev-whataxor`, `rev-unvirtualization` (Very Easy); `cry-babycrypto`, `rev-rap`, `for-1black0white`, `web-smug-dino` (Easy); `cry-collision-course`, `pwn-bigboy` (Moderate); `rev-maze` (Hard). 7 need no target. Chosen from README difficulty labels only. None of them has been run, read or piloted. Isolation checks passed for `pwn-bigboy` and `rev-maze` (the two new targets). |
| Development challenges (piloted, NOT scored) | `rev-checker`, `rev-beleaf`, `rev-tablez`, `pwn-puffin`. The first scored set included `rev-checker`, `rev-beleaf` and `pwn-puffin`; they were swapped out after being piloted, to keep scored and development separate. Disclose prior exposure: the full `rev-checker` flag and partial `rev-beleaf` flag appeared in chat while reading pilot traces; none of the 10 scored challenges was exposed. `msc-showdown` was excluded earlier because its target needs `privileged: true` and the Docker socket. |

## Run status

| Item | Value |
|---|---|
| Attempts finished / running / queued (of 30) | 30 finished (Nov 10), commit `7082312` / tag `frozen-eval-v1`, config `agent`, `claude-haiku-5-5`. Wall-clock 1,261 s total. |
| Where results are | `runs/eval/results.jsonl`, `runs/eval/traces/`, `runs/eval/details/`, `runs/eval/summary.json`, `runs/eval/per_challenge.csv`, console log `runs/eval_console.log` |
| Outcome as recorded | 24 `solved`, 6 `infrastructure_error`, 0 `no_flag`/`wrong_flag`/`timeout`/`budget_exhausted`, 0 `scope_violation`. Overall rate is `null` because 5 challenges are incomplete (summary rule). Of the 24 attempts that ran to a conclusion, all 24 solved. |
| Incidents | 6 x HTTP 429 from the Duke gateway after the client's 2 retries (waits 1 s, 2 s): `rev-rap` t1 and t2, `for-1black0white` t1, `web-smug-dino` t1, `rev-maze` t2, `cry-hybrid2` t3. Two failed at step 0 within 3.5 s (`web-smug-dino` t1, `cry-hybrid2` t3), right after token-heavy attempts. Zero blocked requests, zero scope violations. |
| Tokens (known) | 1,177,441 input + 159,101 output across 30 attempts; 2 attempts have null usage (they failed before any model reply). 201 model calls, 202 tool calls. Heaviest: `rev-maze` (about 164k tokens, 204 s mean). |
| Per-challenge (recorded) | successes of 3: `cry-hybrid2` 2, `rev-whataxor` 3, `rev-unvirtualization` 3, `cry-babycrypto` 3, `rev-rap` 1, `for-1black0white` 2, `web-smug-dino` 2, `cry-collision-course` 3, `pwn-bigboy` 3, `rev-maze` 2. The shortfalls are all infrastructure_error, not agent failures. |

## Trace-driven change

| Item | Value |
|---|---|
| Problem observed (run_id, step numbers) | 6 of 30 attempts ended `infrastructure_error: HTTP 429` (list above), e.g. `agent-rev-rap-t1` (5 steps in), `agent-for-1black0white-t1` (13 steps in), `agent-web-smug-dino-t1` and `agent-cry-hybrid2-t3` (step 0, 3.5 s). Look at the last `llm_error` event in each trace. The client retried only twice, waiting 1 s then 2 s, and ignored any Retry-After header. |
| Hypothesis | A 429 is a transient rate limit. If the client waits longer (exponential up to 60 s, honoring Retry-After, up to 6 retries, 150 s total wait per call), those calls succeed and the 6 slots can be completed, without raising the token budget. |
| Change made | `configs/agent-fix.json` (`config_id = agent-fix`): `llm_retries 6`, `llm_backoff_cap_s 60`, `llm_honor_retry_after true`, `llm_retry_budget_s 150`. Code: `ctfagent/llm.py`, `ctfagent/config.py` (defaults keep the baseline behaviour). 3 new unit tests (baseline gives up after 2 retries; fix survives repeated 429 and honors Retry-After; budget stops waiting). The model, prompt, tools and other limits are unchanged. |
| Follow-up check and result | RUN (Nov 10), config `agent-fix`, output `runs/rerun/` (+ `runs/rerun_console.log`), same 6 slots, run once each, same model/prompt/tools/limits other than the retry policy: **6 of 6 solved, 0 infrastructure errors.** Per slot (baseline -> rerun): `rev-rap` t1 140 s, 147,079 in / 11,273 out, 13 steps; `rev-rap` t2 229 s, 155,998 / 14,735, 14 steps; `for-1black0white` t1 33 s, 20,361 / 4,197, 7 steps; `web-smug-dino` t1 36 s, 20,978 / 2,141, 6 steps; `rev-maze` t2 474 s, 350,968 / 67,367, 28 steps; `cry-hybrid2` t3 43 s, 11,657 / 1,309, 4 steps. Change in outcome on those slots: 0/6 -> 6/6 (+100 percentage points), at the cost of the tokens and time those attempts then used. Merged view (baseline with only those 6 slots replaced): 30/30. Reproduce with `scripts/compare_rerun.py`. The as-recorded baseline stays 24 solved + 6 infrastructure_error and is the official `agent` result. |
| Limits of this check | (1) Six slots, one run each, a few hours after the baseline: the gateway may simply have been less loaded, so this is supporting evidence, not proof that the fix caused the recovery. (2) The client does not log retries, so the traces do not show a 429 happening and being recovered. Next improvement: write an `llm_retry` event (status, wait, attempt) to the trace so a recovery can be cited step by step. (3) `rev-maze` t2 used about 418k tokens, just over the 400k per-attempt cap (the cap is checked before each model call), so a hard challenge can brush against it. (4) Still unconfirmed with the professor whether re-running infrastructure_error slots is acceptable, so report the as-recorded baseline first and the re-run second, labelled. |

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
