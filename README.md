# CTF agent (final project, part 1)

A tool-using CTF solver plus a trusted controller. One fixed configuration (`config_id = agent`) is run
3 times per challenge, and every attempt is written to `results.jsonl` in the course's A4 schema with a JSONL trace.

**Selected configuration:** `configs/agent.json` + `prompts/system.md`. The `model` field is empty on purpose:
set it to an allowed Duke gateway model ID before launching (see step 3).

## What is verified and what is not

| Part | State |
|---|---|
| Agent loop, limits, tool validation, scope tripwire, trace redaction, results records, gateway client | Offline unit tests pass (`python -m unittest discover -s tests`, 31 tests). No live model or target was used. |
| `ComposeEnvironment` (reset, export, solver exec) | **Written from the guide, never run.** It must be adapted to the instructor's `course-compose.yaml`. |
| `challenges.py` (reads nyuctf objects) | **Not run against the real package.** Attribute names are assumptions; confirm them (see "Adaptation points"). |
| Gateway base URL, model ID, quota | **Unknown.** Take them from the Duke AI Gateway guide. |
| Result status `solved` | My choice for a verified solve. Check it against the instructor's `ctf_single_agent_summary.py`. |

## Setup from a clean clone (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests        # offline, no model, no Docker
docker version                                                # server section must respond
git clone https://github.com/NYU-LLM-CTF/NYU_CTF_Bench.git external/NYU_CTF_Bench
git clone https://github.com/NYU-LLM-CTF/CTFTiny.git external/CTFTiny
git -C external/NYU_CTF_Bench rev-parse HEAD                  # record both commits in HANDOFF.md
git -C external/CTFTiny rev-parse HEAD
```

Put the instructor's `course-compose.yaml` in the repo root (or change `environment.compose_file`), and inspect it
before starting anything:

```powershell
docker compose -f course-compose.yaml config --services
docker compose -f course-compose.yaml config --networks
```

### Model access

Keep both values in the controller's environment only. Never put them in the repo, the solver, or a trace.

```powershell
$env:LITELLM_TOKEN    = "<your Duke AI Dashboard key>"
$env:LITELLM_BASE_URL = "<gateway base URL from the Duke AI Gateway guide, ending in /v1>"
```

Run the instructor's `list_gateway_models.py`, pick an allowed model, and set it as `"model"` in `configs/agent.json`.
A listed model is not proof it supports tool calls; the first pilot attempt is that check.

### Evaluation manifest

Choose the 10 scored CTFTiny IDs, list them in `evaluation_ids.txt` (one per line), and build the manifest with the instructor's script:

```powershell
.venv\Scripts\python.exe make_manifest.py --dataset external/CTFTiny/ctftiny.json --ids-file evaluation_ids.txt `
  --split evaluation --source-commit (git -C external/CTFTiny rev-parse HEAD) --out evaluation_manifest.json
```

## Launch

Pilot first. Keep it out of the scored results by using a different `--out`. For development challenges use
`external/NYU_CTF_Bench/development_dataset.json` and a pilot manifest.

```powershell
.venv\Scripts\python.exe scripts/run_attempts.py --manifest pilot_manifest.json `
  --dataset external/NYU_CTF_Bench/development_dataset.json --out runs/pilot --trials 1 --max-attempts 2
```

Scored run (3 trials for each challenge in the manifest, 30 attempts for 10 challenges). Existing slots are skipped:

```powershell
.venv\Scripts\python.exe scripts/run_attempts.py --manifest evaluation_manifest.json `
  --dataset external/CTFTiny/ctftiny.json --config configs/agent.json --out runs/eval --trials 3
.venv\Scripts\python.exe scripts/check_results.py runs/eval/results.jsonl
.venv\Scripts\python.exe ctf_single_agent_summary.py --manifest evaluation_manifest.json `
  --results runs/eval/results.jsonl --config agent --out runs/eval/summary.json --csv runs/eval/per_challenge.csv
```

Output layout: `results.jsonl` (A4 fields only), `traces/<run_id>.jsonl`, `details/<run_id>.json` (config fingerprint,
git commit, model, reset time, file hash inventory, stop reason, step and call counts).

## How it works

```
controller (trusted)                         solver sandbox (container)
  reset target + solver  ───────────────────►  fresh workspace
  export contestant files + sha256 inventory ►  /workspace
  loop: model ─► tool call ─► validate ─► run_shell / read_file via docker exec
        submit_flag ─► verifier in controller ─► "correct" | "incorrect"
  write trace, result record; tear everything down
```

- **Tools** (`ctfagent/tools.py`): `run_shell(command, timeout_s)`, `read_file(path, max_bytes)`, `submit_flag(flag)`.
  Inputs are validated, errors are returned to the model as text, output is capped and truncation is logged.
- **Limits, enforced in code** (`ctfagent/agent.py`, values in `configs/agent.json`): wall-clock per attempt, model steps,
  total tokens, wrong submissions, consecutive no-tool turns, per-tool timeout (also capped by remaining wall-clock). The
  model cannot change any of them.
- **Statuses:** `solved`, `no_flag`, `wrong_flag`, `timeout`, `budget_exhausted`, `infrastructure_error`, `scope_violation`.
  `elapsed_s` is the attempt loop time; reset time is in `details/`.
- **Tokens:** summed from gateway usage; `null` if the gateway reported none; `usage_complete` in `details/` says whether any
  call was missing usage. `cost_usd` is `null` (no price data supplied).
- **Answer separation:** the flag lives only in the controller's `HashVerifier`. The solver receives a sanitized description
  (original CSAW hostnames rewritten to the target name), the contestant files and the target name. A verified flag is
  withheld from the trace. Free text the model writes could still repeat a flag, so check traces of solved runs before sharing.
- **Switch for the improvement test:** `"repeat_hint": true` makes the controller append a note after the same call runs
  3 times. It is off by default; turn it on only as a hypothesis tied to a trace you have observed.

### Controls

The code enforces limits, tool validation, secret redaction and a command-level scope tripwire (`ctfagent/scope.py`: foreign
URLs and IPs in `curl/wget/nc/ssh/...` commands, `remote("host")`). A hit stops the attempt as `scope_violation` and keeps the
trace. **The tripwire is not isolation.** Network isolation, no Docker socket, no sudo and no published ports must come from
the instructor's compose configuration; check it as the guide says (host access, routes, mounts, capabilities). Record the
evidence in the report. This repo does not claim those controls.

## Adaptation points (do these before the first live run)

1. `ctfagent/challenges.py`: confirm `chal.description`, `chal.server_name`, `chal.port`, `chal.files` and the challenge directory
   attribute against the installed `nyuctf` 1.1.1.
2. `ctfagent/environment.py`: align service names, how a challenge is selected (it passes `CHALLENGE_ID` to compose), and the
   workspace path with `course-compose.yaml`.
3. `scripts/run_attempts.py::manifest_ids`: match the real `evaluation_manifest.json` shape.
4. If the instructor supplies a private verifier, implement `Verifier.verify` with it and pass it in place of `HashVerifier`.

## Reuse and AI assistance

The NYU CTF Bench / CTFTiny datasets and the `nyuctf` loader are used as data sources. The control flow follows the
illustrative loop in the course's Implementation Guide (A4). This code base was written with the assistance of Claude
(Anthropic's Claude Code). Add each team member's contribution here before submitting.
