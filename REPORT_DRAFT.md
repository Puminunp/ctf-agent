> **SUPERSEDED (Nov 11):** the submitted report is `REPORT.md`. This file is the earlier draft and is kept only for history. Its cost figures use Anthropic list price; `REPORT.md` uses the Duke price.

# CTF Agent Benchmarking: Part 1 report (draft)

Team: Pumin, JackDeBuff. Repository: https://github.com/Puminunp/ctf-agent (private). Frozen baseline: tag `frozen-eval-v1`, commit `7082312`.
Model: `claude-haiku-5-5` through the Duke AI Gateway. Benchmark: 10 CTFTiny challenges (commit `f1c9531`).

**Status of this draft.** Numbers come from `runs/eval/`, `runs/rerun/` and `runs/baseline_metrics.md`. Text in [brackets] needs the team's input. Cut this to about three pages before submitting.

## 1. Summary

We built a tool-using solver agent and a trusted controller, checked the isolation controls from inside the sandbox, piloted on four development challenges,
froze one configuration (`agent`) and ran it 3 times on each of 10 challenges (30 attempts). 24 attempts solved the challenge. The other 6 were not agent
failures: each stopped on an HTTP 429 rate limit from the gateway after the client's 2 short retries. We traced the problem, changed only the retry policy
(`agent-fix`), and re-ran exactly those 6 slots: 6 of 6 solved. We then ran `agent-fix` fresh on all 30 slots: 30 of 30 solved with 0 infrastructure errors, +20.0 percentage points over the baseline's 80.0% for +558 s, +214k tokens and about +$0.04 (section 5).

## 2. Architecture and controls

- **Controller (trusted).** Resets the target and solver for every attempt, sends only the files listed for the challenge plus a sanitized description and the
  target name, holds the expected flag, verifies submissions locally, and writes a JSONL trace and a result record per attempt.
- **Agent loop.** The model observes the last tool result, chooses a tool, and adjusts. Tools: `run_shell(command, timeout_s)`, `read_file(path, max_bytes)`,
  `submit_flag(flag)`. Inputs are validated; every error returns to the model as text; output is capped and truncation is logged; `submit_flag` answers only
  "correct" or "incorrect". The controller enforces, in code, an attempt wall-clock of 900 s, 60 model steps, 400,000 tokens, 5 wrong flags, 3 idle turns and a
  60 s per-tool timeout. The model cannot change any limit.
- **Isolation.** The solver runs as an unprivileged user with no sudo, all capabilities dropped and no-new-privileges, on an internal Docker network with
  no internet or host access (or no network when the challenge has no target). No Docker socket, no published ports, 2 GB / 1 CPU limits. Targets run from
  the challenge's published image; the upstream compose files (which mount the Docker socket) are never run. `scripts/check_isolation.py` tested 10 checks from inside the
  solver for `rev-checker`, `pwn-puffin`, `pwn-bigboy` and `rev-maze`; all passed (evidence in `runs/controls/`). A command-level tripwire stops an attempt as
  `scope_violation` if it names a foreign URL or IP. Across all traces the count of `scope_violation` events is 0.
- **Answer separation.** The flag exists only in the controller. A verified flag is redacted from the whole trace. Tool output may still contain partial answers,
  so solved traces are kept private. In `agent-for-1black0white-t1` step 7 the agent states it should not pull a library from the internet and writes its own decoder, consistent with the prompt.

## 3. Setup checks and pilots (development, not scored)

| Challenge | Steps | Seconds | Tokens in / out | Outcome |
|---|---|---|---|---|
| rev-checker | 3 | 7.7 | 5,706 / 926 | solved; exposed a bug: the flag stayed in a tool result in the trace (fixed, tested) |
| rev-beleaf | 10 | 49.7 | 83,636 / 8,648 | solved; recovered from its own off-by-one, ran the binary before submitting |
| rev-tablez | 5 | 11.5 | 18,676 / 1,525 | solved |
| pwn-puffin | 4 | 13.0 | 11,161 / 1,003 | solved; first live-target run, reached `target:31140` with `nc` |

Three of these (`rev-checker`, `rev-beleaf`, `pwn-puffin`) had been in the first scored set. They were swapped out before the scored run so no scored challenge was used for development.

## 4. Scored evaluation: baseline `agent` (30 attempts, as recorded)

| Challenge | Difficulty | Solved of 3 | Success | Sample SD (pp) | Mean tokens | Mean s |
|---|---|---|---|---|---|---|
| cry-hybrid2 | Very Easy | 2 | 66.7% | 57.7 | 16,891 | 9.6 |
| rev-whataxor | Very Easy | 3 | 100% | 0.0 | 42,048 | 18.9 |
| rev-unvirtualization | Very Easy | 3 | 100% | 0.0 | 36,570 | 14.5 |
| cry-babycrypto | Easy | 3 | 100% | 0.0 | 16,613 | 10.9 |
| rev-rap | Easy | 1 | 33.3% | 57.7 | 79,763 | 51.0 |
| for-1black0white | Easy | 2 | 66.7% | 57.7 | 44,317 | 53.0 |
| web-smug-dino | Easy | 2 | 66.7% | 57.7 | 25,266 | 19.9 |
| cry-collision-course | Moderate | 3 | 100% | 0.0 | 13,591 | 18.3 |
| pwn-bigboy | Moderate | 3 | 100% | 0.0 | 20,293 | 20.4 |
| rev-maze | Hard | 2 | 66.7% | 57.7 | 164,215 | 203.9 |

| Metric (all attempts counted, infrastructure errors counted as failures) | Baseline |
|---|---|
| Attempts / solved / infrastructure errors | 30 / 24 / 6 |
| Success rate | 80.0% (100.0% if the 6 gateway errors are excluded) |
| Pass@1 / Pass@2 / Pass@3 | 70.0% / 90.0% / 100.0% |
| Solve rate by trial 1 / 2 / 3 | 70 / 80 / 90 %; mean 80.0 %, sample variance 100.0 pp² |
| Wall-clock | 1,261.5 s total, 42.1 s per attempt |
| Model calls / tool calls | 201 / 202 |
| Tokens (known) | 1,177,441 input, 159,101 output (2 attempts have no usage: they failed before any model reply) |
| Estimated cost | about $0.20 at Anthropic list price for claude-haiku-5-5 ($0.10 / $0.50 per million tokens); Duke's billing may differ |

The summary script reports the overall rate as `null` because 5 challenges are incomplete (an incident in them). Three attempts per challenge is limited evidence and the SD is not a confidence interval.

## 5. Problem, hypothesis, change and comparison

**Observed problem.** 6 of 30 baseline attempts ended `infrastructure_error: HTTP 429`: `rev-rap` t1 and t2, `for-1black0white` t1, `web-smug-dino` t1, `rev-maze` t2, `cry-hybrid2` t3.
The client retried twice, waiting 1 s then 2 s, and ignored `Retry-After`. Two attempts (`web-smug-dino` t1, `cry-hybrid2` t3) failed at step 0 within 3.5 s, right after token-heavy attempts. Others died mid-work: `for-1black0white` t1 was lost at its 13th model call.

**Hypothesis.** A 429 is transient. Retrying with longer waits (up to 6 retries, waits up to 60 s, honoring `Retry-After`, at most 150 s of waiting per call) lets those calls succeed without changing the model, prompt, tools or limits.

**Change.** Config `agent-fix`; the baseline's behaviour is unchanged by default. Three unit tests cover it (baseline gives up after 2 retries; the fix survives repeated 429s and honors `Retry-After`; the retry budget stops waiting).

**Controlled comparison: `agent` vs `agent-fix`, each run on all 10 challenges x 3 trials** (30 attempts each, fresh state for every attempt; `agent-fix` ran at commit `2619f77`, the baseline at `7082312`; `scripts/compare_configs.py`, plots in `runs/plots/`).

| Metric (all attempts counted) | `agent` | `agent-fix` | Change |
|---|---|---|---|
| Attempts solved | 24 of 30 | **30 of 30** | |
| Infrastructure errors (HTTP 429) | 6 | 0 | -6 |
| Success rate | 80.0% | 100.0% | **+20.0 percentage points** |
| Success rate excluding infrastructure errors | 100.0% | 100.0% | +0.0 pp |
| Pass@1 / Pass@2 / Pass@3 | 70 / 90 / 100% | 100 / 100 / 100% | +30 / +10 / +0 pp |
| Solve rate by trial 1 / 2 / 3 | 70 / 80 / 90% | 100 / 100 / 100% | |
| Mean solve rate, sample variance | 80.0%, 100.0 pp² | 100.0%, 0.0 pp² | +20.0 pp, -100.0 pp² |
| Wall-clock, total | 1,261.5 s (42.1 s per attempt) | 1,819.6 s (60.7 s per attempt) | +558.1 s (+44%) |
| Model calls / tool calls | 201 / 202 | 225 / 225 | +24 / +23 |
| Tokens in / out | 1,177,441 / 159,101 | 1,350,462 / 199,866 | +213,786 total (+16%) |
| Estimated cost (list price) | $0.197 | $0.235 | +$0.038 |

Successes out of 3 per challenge, `agent` then `agent-fix`: `cry-hybrid2` 2 / 3, `rev-rap` 1 / 3, `for-1black0white` 2 / 3, `web-smug-dino` 2 / 3, `rev-maze` 2 / 3; every other challenge 3 / 3 in both. Largest `agent-fix` attempt: `rev-maze` t3, 22 steps, 298,374 tokens, 537.9 s, under the 400,000 / 900 s limits.

**Where the extra time and tokens went.** The six slots that stopped on a 429 in the baseline stopped early, so the baseline never paid for them. In `agent-fix` they all finished (trace step counts): `rev-rap` t1 in 10 steps (baseline stopped after 5), `rev-rap` t2 in 12 (stopped after 5), `for-1black0white` t1 in 8 (stopped after 13), `web-smug-dino` t1 in 5 (stopped before the first model reply), `rev-maze` t2 in 19 (stopped after 11), `cry-hybrid2` t3 in 4 (stopped before the first model reply). On the 24 slots that finished in both runs, `agent-fix` used about 5% fewer tokens (1,043,355 vs 1,099,881) but about 34% more wall-clock time (1,262 s vs 940 s). More waiting with fewer tokens is consistent with `agent-fix` waiting through rate limits, but retries are not logged, so no trace step proves it, and run-to-run variation in the model's own trajectories also changes the length of individual attempts ( for example `for-1black0white` averaged 34.5 s in the baseline's finished attempts and 65.5 s in `agent-fix`).

**Earlier, smaller check.** Before the full run, re-running only the 6 failed slots once under `agent-fix` also gave 6 of 6 (`runs/rerun/`, `scripts/compare_rerun.py`).

**What this does and does not show.** The effect on solve rate is measured: +20.0 pp, all of it from removing the 6 gateway losses, since the unchanged agent solved every attempt that ran to a conclusion. It supports the hypothesis but does not prove it: the two runs took place on different days and loads, so a quieter gateway could also explain fewer 429s, and the traces do not log retries. Both configurations sit at or near the ceiling on these 10 challenges, so this comparison measures robustness to rate limits, not problem-solving skill.

## 6. Failure analysis and limitations

**Annotated case: `agent-for-1black0white-t1`.** Steps 1 to 5: the agent inspected `qr_code.txt`, found 29 rows of 29-bit numbers and recognised a QR code. Steps 6 to 7: no imaging or QR library was installed, so it wrote its own decoder instead of fetching one. Steps 8 to 12: it decoded text with one wrong character, tried to fix it with Reed-Solomon error correction, rewrote that code once and began brute-forcing a bit flip. After 13 completed model calls (about 90 s in, 69,578 input tokens spent) the 14th call got a 429 twice in a row and the attempt ended as `infrastructure_error`. Under `agent-fix` the same slot solved in 8 steps. The agent's approach was sound; the loss was infrastructure. Testable improvement: log each retry as an `llm_retry` event (status, wait, attempt) and count attempts lost to transient errors per 30 attempts: baseline 6, `agent-fix` expected 0.

**Limitations and weaknesses**
- The agent solved every attempt that ran to a conclusion (24 of 24). The easy and moderate challenges give little signal about where it fails; harder challenges or a harder set are needed before the final.
- Two earlier launches of the full `agent-fix` run were harness failures, not results, and are kept in the repository: the first failed in 0.3 s per attempt because Docker Desktop's engine had stopped (30 records, 0 tokens, `runs/fix_aborted_docker_down/`); the second failed after about 3.5 minutes per attempt because the gateway was unreachable from the machine, and was stopped after 7 records (`runs/fix_aborted_network_down/`). The third launch, over the Duke VPN, is the reported run (`runs/fix/`).
- Token use grows with every step because the history is re-sent: input per call rose from 1.4k to 12.7k on `rev-beleaf`. The heaviest `agent-fix` attempt (`rev-maze` t3, 298k tokens) is within the 400k cap, but an earlier `rev-maze` re-run reached about 418k, just over it, because the cap is checked before each model call.
- Reaching the gateway needed the Duke VPN or a Duke network at times. The gateway was unreachable (connection timeout on port 443) while the VPN was off.
- Cost is an estimate at list price; the Duke gateway may bill differently. Only one small model was tested.
- Retries are not logged. The Windows setup needed workarounds (the datasets contain a folder named `get_it?`, so a `git clone` fails on Windows; we used the GitHub ZIP).

## 7. Configuration for the final (Nov 18) and trade-off

Carry `agent-fix` (`configs/agent-fix.json`, launched with `scripts/run_attempts.py --config configs/agent-fix.json`). It changes only the retry policy; in the full comparison it lost no attempt to a rate limit (0 vs 6) and solved 30 of 30. Trade-off: a call can now wait up to 150 s, which spends wall-clock time (the attempt limit stays 900 s). Before the competition: log retries, consider trimming old tool output to cut tokens on hard challenges, and test a stronger model on Moderate and Hard challenges against practice challenges for regressions.

## 8. Prior exposure and disclosures

- `rev-checker` (full flag) and `rev-beleaf` (partial flag) were shown in the working chat while reading pilot traces; both were development challenges by then. None of the 10 scored challenges was run or read before the scored run. While analysing the failure above, a partial decoded string of the `for-1black0white` flag appeared in the chat after the scored runs; it did not affect any score.
- `msc-showdown` was left out because its target needs a privileged container and the Docker socket.
- Several API keys were pasted into the chat during development; they should be (and, once done, will be) revoked. No key is in the repository or any trace.

## 9. Contributions and AI assistance

- [Pumin: state your contribution, for example running and monitoring the evaluation, choosing challenges and decisions.]
- [Jack: state your contribution, for example the report, analysis and video.]
- AI assistance: the code, scripts, tests and drafts of this document were written with Claude Code (Anthropic's Claude), directed by the team, who ran and reviewed the work. The runtime agent model is `claude-haiku-5-5` via the Duke AI Gateway.
- Reused: NYU CTF Bench and CTFTiny data, the `nyuctf` loader (version 1.1.1), Duke's AI Gateway developer guide, and the control flow of the course Implementation Guide.

## 10. Reproduce

```
.venv\Scripts\python.exe -m unittest discover -s tests
docker build -t ctf-solver:latest docker/solver
.venv\Scripts\python.exe scripts/run_attempts.py --manifest evaluation_manifest.json --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json --config configs/agent.json --out runs/eval --trials 3
.venv\Scripts\python.exe scripts/summarize.py --manifest evaluation_manifest.json --results runs/eval/results.jsonl --config agent --out runs/eval/summary.json --csv runs/eval/per_challenge.csv
.venv\Scripts\python.exe scripts/compare_rerun.py --baseline runs/eval --rerun runs/rerun --out runs/rerun/comparison.json
```
Selected configuration for the final: `configs/agent-fix.json`.
