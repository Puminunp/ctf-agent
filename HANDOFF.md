# HANDOFF: Part 1 is done, Part 2 starts here (updated Nov 10, night)

> **UPDATE Nov 11:** Jack pushed the final report (`REPORT.md`) and the demo run for the video (`runs/demo/`, `agent-fix` on `rev-checker`, solved in 3 steps, 6.7 s). `REPORT_DRAFT.md` is superseded. His per-challenge table, pass@k, token and time numbers match the raw records (checked). Open items from the review are listed in the team chat; see also the cost-price note: `REPORT.md` uses $0.05 in / $0.25 out per million tokens ("Duke price"), while the older notes here use Anthropic list price ($0.10 / $0.50).

Deadline: **Wed Nov 11, 2026, 11:59 p.m. Eastern.** Aim to submit by about 8 p.m. Repo: https://github.com/Puminunp/ctf-agent (private).
Read this file first, then `README.md`, then `REPORT.md`. The shared checklist page is https://claude.ai/artifact/FhoQRbmdLnckKTp6WtEVM8.

## 1. Where things stand

| Item | State |
|---|---|
| Agent, tools, limits, tracing, local flag check | Done. 56 offline tests pass. |
| Isolated environment and controls evidence | Done (`runs/controls/`, 4 challenges, all checks passed). |
| Pilots on 4 development challenges | Done, 4 of 4 solved. |
| Scored baseline `agent` (30 attempts) | Done: 24 solved, 6 HTTP 429 gateway errors, 0 agent failures. |
| Fix `agent-fix` (retry policy only) and its full run (30 attempts) | Done: 30 solved, 0 errors. |
| Comparison, metrics, plots | Done (`runs/comparison.md`, `runs/comparison.json`, `runs/plots/*.png`). |
| Report | **Draft** in `REPORT_DRAFT.md`. Needs trimming to about 3 pages, plots inserted, contribution statements. |
| Video of a fresh successful run | **Not done** (Paul will record it). |
| Clean-clone README check | **Not done** (Jack). |
| Canvas package | **Not done** (both). |

The professor's last message (Nov 10): no instructor infrastructure exists, so we use the CTFTiny files, verify flags locally, choose our own 10 challenges, and the helper scripts
are optional. The assignment text he re-posted is the ORIGINAL rubric, so it applies: controlled comparison (20 pts), pass@1/2/3, average solve rate and variance, time, calls,
tokens, cost, solve-rate change in percentage points with trace citations, failure analysis, and a video or demo of a SUCCESSFUL fresh run (3 pts).

## 2. Results (all attempts counted, infrastructure errors counted as failures)

| Metric | `agent` (baseline) | `agent-fix` | Change |
|---|---|---|---|
| Attempts solved | 24 of 30 | 30 of 30 | |
| Infrastructure errors (HTTP 429) | 6 | 0 | -6 |
| Success rate | 80.0% | 100.0% | +20.0 percentage points |
| Success rate excluding infrastructure errors | 100.0% | 100.0% | +0.0 pp |
| Pass@1 / @2 / @3 | 70 / 90 / 100% | 100 / 100 / 100% | +30 / +10 / +0 pp |
| Solve rate by trial 1 / 2 / 3 | 70 / 80 / 90% | 100 / 100 / 100% | |
| Mean solve rate, sample variance | 80.0%, 100.0 pp² | 100.0%, 0.0 pp² | |
| Wall-clock | 1,261.5 s (42.1 s per attempt) | 1,819.6 s (60.7 s per attempt) | +558.1 s |
| Model calls / tool calls | 201 / 202 | 225 / 225 | +24 / +23 |
| Tokens in / out | 1,177,441 / 159,101 | 1,350,462 / 199,866 | +213,786 |
| Estimated cost | $0.197 | $0.235 | +$0.038 |

Cost is an ESTIMATE at Anthropic list price for `claude-haiku-5-5` ($0.10 in / $0.50 out per million tokens, prompts under 100K tokens, no caching). Duke's billing may differ.

Successes out of 3 (baseline, then fix): `cry-hybrid2` 2, 3; `rev-rap` 1, 3; `for-1black0white` 2, 3; `web-smug-dino` 2, 3; `rev-maze` 2, 3; all others 3, 3
(`rev-whataxor`, `rev-unvirtualization`, `cry-babycrypto`, `cry-collision-course`, `pwn-bigboy`). The baseline's official summary reports the overall rate as `null` because 5 challenges
are incomplete (an incident in each); that is the rule, not a bug.

**Interpretation to keep honest.** The only difference between the configs is the gateway retry policy. All of the +20 pp comes from removing the 6 rate-limit losses; the unchanged agent
solved every attempt that ran to a conclusion (24 of 24). The runs happened on different days, so a quieter gateway could partly explain fewer 429s, and retries are not logged, so no
trace step proves a 429 was absorbed. On the 24 slots that finished in both runs, `agent-fix` used about 5% fewer tokens (1,043,355 vs 1,099,881) and about 34% more wall-clock time
(1,262 s vs 940 s), consistent with waiting through rate limits but not proof. Both configs are at the ceiling on these 10 challenges, so this measures robustness, not skill.

## 3. Configuration and reproducibility

| Item | Value |
|---|---|
| Baseline | `configs/agent.json`, `config_id = agent`, tag `frozen-eval-v1` (commit `7082312`), output `runs/eval/` |
| Selected for the final (Nov 18) | `configs/agent-fix.json`, `config_id = agent-fix`, commit `2619f77`, output `runs/fix/` (no attempt flagged dirty) |
| Difference | `llm_retries` 2 -> 6, `llm_backoff_cap_s` 8 -> 60, `llm_honor_retry_after` false -> true, `llm_retry_budget_s` unlimited -> 150 |
| Model | `claude-haiku-5-5` via `https://litellm.oit.duke.edu/v1` (needs the Duke VPN or a Duke network) |
| Prompt, tools, other limits | identical: `prompts/system.md`; 900 s, 60 steps, 400k tokens, 5 wrong flags per attempt |
| Scored challenges (10, from CTFTiny commit `f1c9531`) | `cry-hybrid2`, `rev-whataxor`, `rev-unvirtualization` (Very Easy); `cry-babycrypto`, `rev-rap`, `for-1black0white`, `web-smug-dino` (Easy); `cry-collision-course`, `pwn-bigboy` (Moderate); `rev-maze` (Hard) |
| Development challenges (not scored) | `rev-checker`, `rev-beleaf`, `rev-tablez`, `pwn-puffin` |
| Launch command | README, "Launch command for the selected configuration" |
| Pinned dependencies | `requirements.txt` (`nyuctf==1.1.1`), `requirements-plots.txt` (matplotlib 3.11.2, numpy 2.5.4). Not pinned: the pip packages inside `docker/solver/Dockerfile` (optional to fix). |

Metrics scripts: `scripts/check_results.py`, `scripts/summarize.py` (per challenge: success rate, sample SD, mean tokens and time), `scripts/compare_configs.py`
(two configs, pass@k, variance, calls, tokens, cost, change in pp), `scripts/compare_rerun.py` (same-slot comparison), `scripts/make_plots.py`, `scripts/show_trace.py`.

## 4. Incidents and records (keep these in the report)

- **6 x HTTP 429** in the baseline: `rev-rap` t1 and t2, `for-1black0white` t1, `web-smug-dino` t1, `rev-maze` t2, `cry-hybrid2` t3. The client retried twice (waits 1 s, 2 s) and ignored `Retry-After`.
  Two failed at step 0 within 3.5 s. Annotated case for the report: `agent-for-1black0white-t1` (13 completed model calls, 14th call failed; same slot solved in 8 steps under `agent-fix`).
- **Earlier 6-slot re-run** under `agent-fix` (`runs/rerun/`): 6 of 6 solved. Superseded by the full run, still valid as an earlier check.
- **Two failed launches of the full `agent-fix` run**, kept as incident records, not results: `runs/fix_aborted_docker_down/` (Docker engine stopped, 30 records at 0.3 s, no tokens) and
  `runs/fix_aborted_network_down/` (gateway unreachable without VPN, 7 records at about 210 s each, no tokens). The third launch is the reported one.
- Scope violations: 0. Blocked requests by the agent: none observed. In `agent-for-1black0white-t1` step 7 the agent says it should not fetch a library from the internet and writes its own decoder.
- Pilots (development): `rev-checker` 3 steps, 7.7 s, 5,706 / 926 tokens (found a real bug: the flag stayed in a tool result in the trace, now redacted across the whole trace once verified);
  `rev-beleaf` 10 steps, 49.7 s, 83,636 / 8,648; `rev-tablez` 5 steps, 11.5 s, 18,676 / 1,525; `pwn-puffin` 4 steps, 13.0 s, 11,161 / 1,003 (first live-target run).

## 5. Controls evidence

Solver: non-root, no sudo, all capabilities dropped, no-new-privileges, internal Docker network (no internet, no host), no Docker socket, no published ports, 2 GB / 1 CPU / 512 pids.
`scripts/check_isolation.py` ran 9 to 10 checks from inside the solver for `rev-checker`, `pwn-puffin`, `pwn-bigboy`, `rev-maze`: all passed (`runs/controls/isolation_*.json`).
The answer key is held only by the controller; the solver gets the listed contestant files, a sanitized description and the target name. Challenge folders also hold `flag.txt`, server
source and sometimes `solve.txt`; none of that is exported (checked). `msc-showdown` was excluded because its target needs a privileged container and the Docker socket.

## 6. Disclosures to put in the report

- **Prior exposure:** the full `rev-checker` flag and part of the `rev-beleaf` flag appeared in the working chat while reading pilot traces (both were development challenges by then). After the
  scored baseline, a partial decoded string of the `for-1black0white` flag appeared while writing the failure analysis; it did not affect any score. None of the 10 scored challenges was run or read before the scored run.
- Three challenges from the first scored set (`rev-checker`, `rev-beleaf`, `pwn-puffin`) were piloted, so they were swapped out before the scored run.
- Several API keys were pasted into the chat; revoke them all in the Duke dashboard. No key is in the repo, a trace or a result file (scanned).
- Code, scripts, tests and the report draft were written with Claude Code assistance; cite it. Reused: NYU CTF Bench and CTFTiny data, the `nyuctf` loader, Duke's AI Gateway guide.
- Solved-run traces redact the full flag but keep partial fragments the agent printed. Keep the repo private; do not paste scored traces into slides or the video.

## 7. What is left

**Jack** (the report `REPORT.md` and a demo run in `runs/demo/` are already pushed; his numbers were checked against the raw records on Nov 11)
1. Cost price: cite the source of the $0.05 in / $0.25 out per million tokens ("Duke price") used in `REPORT.md`, or use one price consistently. The repo's other notes and `scripts/compare_configs.py` use Anthropic list price ($0.10 / $0.50).
2. Verify the temperature claim in `REPORT.md` (gateway accepts temperature 3.5). It is not re-verified by anyone else.
3. Demo sentence in section 8 of `REPORT.md`: update it to the final video (run ID, commit, machine, narration) once Paul has recorded it.
4. Convert `REPORT.md` to a PDF (or Word file), check it is about 3 pages, and confirm the four plots render.
5. Clean-clone test: on Nov 11 a fresh clone was tested by the repo owner (56 tests pass, shipped results validate), but a Windows clean-clone test of the live setup by Jack has not been confirmed.
6. Optional: pin the pip packages in `docker/solver/Dockerfile`.

Already applied in `REPORT.md` on Nov 11: the extra disclosures (three swapped challenges, the `for-1black0white` partial exposure, the "52 to 53 of 54" wording), the incident sentence for the two failed launches, both cost prices, and the four plots.

**Paul**
1. Record the video (3 minutes max): one fresh run, a short development challenge such as `rev-tablez`, config `agent-fix`, `--out runs/demo_video`; show commit, challenge ID, run ID, tool activity, the controller's confirmation; disclose any cuts; keep the key and scored traces off screen. Push `runs/demo_video` and send Jack the run ID, commit and video link.
2. Approve your contribution statement in `REPORT.md`; revoke your API keys afterward.

**Both**
- Merge the report, add each member's contribution and the AI-assistance and reuse statements, tag the submitted commit (for example `git tag submission-v1`), and submit in Canvas by about 8 p.m.:
  private GitHub link, a zip as a backup, the report and the video.

## 8. Rules

- Do not read flags, solutions or write-ups of the scored challenges. Do not open `runs/eval/traces` or `runs/fix/traces` to look for answers.
- Never put an API key in the repo, a trace, the video or the report. Set `LITELLM_TOKEN` in the PowerShell window only.
- Do not edit `runs/eval/` (the as-recorded baseline) or the frozen config files; state changes as a new config.
- Describe an untested change as "proposed", not "measured".

## 9. File map

`ctfagent/` agent, controller, tools, environment, tracing; `configs/` two configs; `prompts/system.md`; `scripts/` run, check, summarize, compare, plot, trace viewer; `tests/` 56 offline tests;
`docker/solver/Dockerfile`; `evaluation_ids.txt` and `evaluation_manifest.json`; `runs/eval`, `runs/fix`, `runs/rerun`, `runs/controls`, `runs/plots`, `runs/comparison.*`, `runs/baseline_metrics.*`;
`runs/fix_aborted_*` incident records; `REPORT_DRAFT.md`; `README.md`.
