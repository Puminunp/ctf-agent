# CTF agent (final project, part 1)

A tool-using CTF solver plus a trusted controller. Two configurations are compared, each run 3 times on each of 10 challenges
(30 attempts). Every attempt is written to `results.jsonl` in the course's A4 schema with a JSONL trace.

| Config | File | `config_id` | Recorded at | Result (30 attempts) |
|---|---|---|---|---|
| Baseline | `configs/agent.json` | `agent` | tag `frozen-eval-v1` (commit `7082312`), output `runs/eval/` | 24 solved, 6 HTTP 429 errors |
| **Selected for the final** | `configs/agent-fix.json` | `agent-fix` | commit `2619f77`, output `runs/fix/` | 30 solved, 0 errors |

Both use `prompts/system.md`, model `claude-haiku-5-5` through the Duke AI Gateway, and the same tools and limits. The only
difference is the gateway retry policy (`agent-fix`: up to 6 retries, waits up to 60 s, honors `Retry-After`, 150 s total wait per call).

Two caveats, both also in `REPORT.md`: (1) the configs request `temperature: 0.0`, but a direct test reported in `REPORT.md` found the Duke gateway
accepts any temperature (even 3.5), which suggests it is not applied to `claude-haiku-5-5`, so runs are not repeatable step by step (this was not
re-verified by the repo owner); (2) cost is an estimate: `REPORT.md` uses $0.05 in / $0.25 out per million tokens (Duke's price), while `scripts/compare_configs.py`
uses Anthropic's list price ($0.10 / $0.50), so its totals ($0.197 and $0.235) are twice the report's ($0.099 and $0.117).

**Launch command for the selected configuration** (PowerShell, Docker Desktop running, Duke VPN or network connected, `LITELLM_TOKEN` set):

```powershell
.venv\Scripts\python.exe scripts/run_attempts.py --manifest evaluation_manifest.json `
  --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json --config configs/agent-fix.json --out runs/fix --trials 3
```

Comparison, metrics and plots (pass@k, solve rate and variance, calls, tokens, cost, change in percentage points):

```powershell
.venv\Scripts\python.exe scripts/compare_configs.py --manifest evaluation_manifest.json --a runs/eval --b runs/fix --out runs/comparison.json --md runs/comparison.md
uv pip install -r requirements-plots.txt --python .venv\Scripts\python.exe   # once (a uv venv has no pip)
.venv\Scripts\python.exe scripts/make_plots.py --manifest evaluation_manifest.json --a runs/eval --b runs/fix --out runs/plots
```

The report is `REPORT.md` (`REPORT_DRAFT.md` is an earlier draft, superseded); the hand-off notes are `HANDOFF.md`. The demo run for the video is in `runs/demo/`. `runs/fix_aborted_docker_down/` and
`runs/fix_aborted_network_down/` hold two failed launches (Docker stopped; gateway unreachable) kept as incident records, not results.

> The professor confirmed on Nov 9 that the guide's "kit" (`course-compose.yaml`, private verifier, helper scripts, shared
> Linux machine) was an artifact of writing the guide, and that implementation follows the NYU repos. So the isolated
> environment, manifest builder, flag verifier and summary script here are our own.

## What is verified and what is not

| Part | State |
|---|---|
| Agent loop, limits, tool validation, scope tripwire, trace redaction, results records, gateway client, manifest and summary scripts | 47 offline unit tests pass (`python -m unittest discover -s tests`). |
| Gateway + tool calling | `scripts/check_toolcall.py` passed for `claude-haiku-5-5` (Nov 9). |
| Isolated environment (generated compose, solver image) | `scripts/check_isolation.py` passed all controls on `rev-checker` (no target) and `pwn-puffin` (with target). Evidence in `runs/controls/`. |
| nyuctf loader | Run against `pwn-puffin`; fields match the code. |
| A full agent attempt (model + container + verifier end to end) | One pilot on `rev-checker` (Nov 9): solved in 3 steps, 7.7 s, 5,706 in / 926 out tokens. It is a smoke test, not a score (`runs/pilot/`, git-ignored). Read any trace with `scripts/show_trace.py <trace.jsonl>`. |
| Flag verification | `HashVerifier` compares against `chal.flag` inside the controller. No external verifier exists. |
| Result status `solved` | Our name for a verified solve; `scripts/summarize.py` and `scripts/check_results.py` use it. |

## Setup (Windows, PowerShell, from this folder)

```powershell
uv venv --python 3.12 .venv
uv pip install -r requirements.txt --python .venv\Scripts\python.exe
.venv\Scripts\python.exe -m unittest discover -s tests            # offline: no model, no Docker
docker version                                                    # Server section must respond
docker build -t ctf-solver:latest docker/solver                   # solver sandbox image (~1.2 GB)
```

(`python -m venv .venv` works instead of `uv` where Python is installed normally.)

### Data (Windows needs the ZIP route)

A plain `git clone` of CTFTiny or NYU_CTF_Bench fails on Windows: each has a challenge folder named `get_it?`, and `?` is not
allowed in Windows file names, so Git aborts the checkout and leaves an empty working tree. For CTFTiny, download
`https://github.com/NYU-LLM-CTF/CTFTiny/archive/refs/heads/main.zip` and extract it with `tar -xf` into its own folder under
`external/ctftiny_files/` (it skips the bad name). Used commit: `f1c9531672c45b24b7fb5f3aa44a7ac33d3602f8` (GitHub `main`, Nov 9).
NYU_CTF_Bench (development split) is too large for this route; use Linux/WSL2 for it.

### Model access

Create a key at https://dashboard.ai.duke.edu/ (AI Gateway tab, Create Api Key, fund code blank). Keep it in the
controller's environment only; never in the repo, the solver, a trace or a video.

```powershell
$env:LITELLM_TOKEN = "<your key>"      # base URL defaults to https://litellm.oit.duke.edu/v1
.venv\Scripts\python.exe scripts/list_models.py
.venv\Scripts\python.exe scripts/check_toolcall.py --model claude-haiku-5-5
```

Model IDs can contain spaces (for example `GPT 4.1`); copy them exactly into `configs/agent.json`.

## Run

```powershell
# 1. manifest of the 10 scored CTFTiny challenges (reads the index and README labels only, never challenge.json)
.venv\Scripts\python.exe scripts/make_manifest.py --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json `
  --ids-file evaluation_ids.txt --split evaluation --source-commit f1c9531672c45b24b7fb5f3aa44a7ac33d3602f8 --out evaluation_manifest.json

# 2. controls evidence (run once with a target and once without; keep runs/controls/)
.venv\Scripts\python.exe scripts/check_isolation.py --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json --challenge pwn-puffin --out runs/controls

# 3. pilot: one attempt, kept out of the scored results
.venv\Scripts\python.exe scripts/run_attempts.py --manifest evaluation_manifest.json --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json `
  --only rev-checker --trials 1 --max-attempts 1 --out runs/pilot

# 4. scored run: 3 trials for each challenge (30 attempts). Existing slots are skipped, never overwritten or silently retried.
.venv\Scripts\python.exe scripts/run_attempts.py --manifest evaluation_manifest.json --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json `
  --config configs/agent.json --out runs/eval --trials 3

# 5. check and summarize
.venv\Scripts\python.exe scripts/check_results.py runs/eval/results.jsonl
.venv\Scripts\python.exe scripts/summarize.py --manifest evaluation_manifest.json --results runs/eval/results.jsonl `
  --config agent --out runs/eval/summary.json --csv runs/eval/per_challenge.csv
```

Output layout: `results.jsonl` (A4 fields only), `traces/<run_id>.jsonl`, `details/<run_id>.json` (config fingerprint, git commit,
model, reset time, file hash inventory, stop reason, step and call counts), `compose/` (the generated compose file per challenge).

## How it works

```
controller (trusted, holds the flag)          solver container (unprivileged)
  generate compose, reset target + solver ───►  fresh /workspace
  tar the contestant files into /workspace  ──►  only the files listed in challenge.json
  loop: model -> tool call -> validate -> run_shell / read_file (docker exec)
        submit_flag -> HashVerifier in controller -> "correct" | "incorrect"
  write trace + result record; tear everything down (docker compose down -v)
```

- **Tools** (`ctfagent/tools.py`): `run_shell(command, timeout_s)`, `read_file(path, max_bytes)`, `submit_flag(flag)`. Inputs are
  validated, errors go back to the model as text, output is capped and truncation is logged.
- **Limits, enforced in code** (`ctfagent/agent.py`, values in `configs/agent.json`): wall-clock per attempt, model steps, total
  tokens, wrong submissions, consecutive no-tool turns, per-tool timeout (also capped by the remaining wall-clock). The model cannot change them.
- **Statuses:** `solved`, `no_flag`, `wrong_flag`, `timeout`, `budget_exhausted`, `infrastructure_error`, `scope_violation`.
  `elapsed_s` is the attempt loop time; reset time is in `details/`.
- **Tokens:** summed from gateway usage; `null` if none reported. `cost_usd` is `null` (no price data).
- **Answer separation:** the solver gets a sanitized description (original CSAW hostnames rewritten), only the files in the
  challenge's `files` list, and the target name. Challenge folders also hold `flag.txt`, server source and sometimes `solve.txt`;
  none of that is exported (checked by `check_isolation.py`). Once a flag is verified the full flag string is redacted from the whole trace (tool output and
  model text included, found by the pilot, which printed the flag in a tool result). Partial fragments of it that the agent
  printed along the way are NOT redacted (the `rev-beleaf` pilot trace shows most of the flag in earlier steps), so treat traces of
  solved runs as containing partial answers: keep them private and do not paste them into chats or slides. Traces written before that fix, such as
  `runs/pilot/`, contain the flag in clear; do not share them.
- **Improvement switch:** `"repeat_hint": true` appends a controller note after the same call has run 3 times. Off by default; enable it
  only as a hypothesis tied to a trace you have observed, in a separate config with its own `config_id` and output folder.

### Controls (what the generated compose does)

| Control | How |
|---|---|
| No internet, no host access | solver sits on an `internal: true` network (or `network_mode: none` when the challenge has no target). Checked from inside: `https`, raw IP and `host.docker.internal` all fail. |
| No Docker socket, no sudo, no privileges | not mounted; no `sudo` binary; solver runs as uid 1000 with `cap_drop: ALL` and `no-new-privileges`. |
| No published ports | the generated file has no `ports:`. The upstream challenge compose files publish ports and mount `/var/run/docker.sock`, so they are read only for the image name and never run. |
| Resource limits | 2 GB memory, 1 CPU, 512 pids per container. |
| Reset between attempts | `docker compose down -v` before and after each attempt; workspace is not a bind mount. |
| Command tripwire | `ctfagent/scope.py` stops an attempt as `scope_violation` if a command names a foreign URL or IP. This is a tripwire, not the control. |

Unsupported: challenges whose compose file has `build:` and no `image:`. Challenges that need a privileged target or the Docker
socket (for example `msc-showdown`) were left out of the scored set for that reason.

## Reuse and AI assistance

The NYU CTF Bench / CTFTiny data and the `nyuctf` loader are used as data sources. The control flow follows the illustrative
loop in the course's Implementation Guide (A4). This code base was written with the assistance of Claude (Anthropic's Claude
Code). Add each team member's contribution here before submitting.
