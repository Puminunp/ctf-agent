# Duke AI CTF — Lessons Learned

**Team:** Supawich Puengdang (HTB: JackDeBuff) + Paul Prommark · **Event:** HTB "Duke AI CTF" (event id 3755), Nov 17–19 2026 · **Agent:** our autonomous CTF solver driven by models on the Duke AI gateway (LiteLLM, OpenAI-compatible).
**Result (Nov 18, live):** **12 / 16 solved · rank 6 of 29 teams · ~7,775 pts** · compete marks maxed (5+ solves) · spend ~$23 of the $25 team key.

> This is the knowledge dump from the live run — findings, mistakes, and model behaviour — for the report and so Paul doesn't repeat the same mistakes. Everything here is verified from traces/results, not guessed.

---

## 0. Where the money went — the costly mistakes (with evidence)

**89% of the budget bought nothing.** Local estimate: **~$31 of compute, of which only ~$3.49 produced the 12 solves — $27.80 (89%) was spent on attempts that solved nothing.** (The gateway's authoritative figure is lower, ~$23 real, because the token estimate over-counts; the *proportions* below are the lesson.)

### Spend vs. result, per model
| model | $ spent | attempts | solves | verdict |
|-------|--------:|---------:|-------:|---------|
| Haiku | $0.08 | 7 | 4 | **best ROI — 4 solves for 8 cents** |
| GPT-open (5.3 + internet) | $0.07 | 1 | 1 | TrustPath for 7 cents (once internet was on) |
| DeepSeek-Pro | $7.05 | 14 | 4 | workhorse, good value |
| Sonnet | $2.91 | 12 | 2 | solved 2 non-exploit insanes |
| **GPT-6-luna** | **$15.34** | 6 | 1 | **the single biggest drain — ~$12 of it on 4 unwinnable hard challenges at $3/attempt** |
| gpt-5.3-codex | $4.06 | 5 | **0** | spent like a strong model, **0 solves on the hard tier** |
| DeepSeek-Flash | $1.42 | 5 | 0 | cheap at least |
| GPT-6-sol | $0.21 | 15 | 0 | content-filtered — failed *cheaply* |
| Opus | $0.15 | 5 | 0 | content-filtered — failed *cheaply* |

**Wasted spend by failure type:** `budget_exhausted` **$13.26** + `timeout` **$7.34** = **$20.60** (two-thirds of all waste) went to *engaged-but-couldn't-solve* on the 4–5 hardest challenges. `no_flag` $3.58, `infrastructure_error` $2.71, `wrong_flag` $0.89, `scope_violation` $0.01.

### The three mistakes that actually cost credit
1. **Running EXPENSIVE models at a $3/attempt cap on the unwinnable hardest challenges.** This is where the money died — **$20.60** in `budget_exhausted` + `timeout`. **GPT-6-luna alone burned ~$15** for a single solve; ~$12 of that was four hard pwn/insane it was never going to crack at $3 a pop. **→ Grind the hardest challenges with the *cheap* model (flash ≈ $0.5–1/run); reserve expensive models for *winnable* targets you've identified** (luna's $0.17 twisted-cloud solve is that model used right).
2. **Internet off by default — "insanely" costly design choice.** Every attempt on the osint challenge (Ridiculed) and the cert-callback challenge (TrustPath) *inside the sandbox* was **doomed before it started** — those categories physically cannot be solved without internet. We burned attempts across **6 models** on Ridiculed and many on TrustPath before flipping internet on; TrustPath then solved **in 44 seconds for $0.07.** **→ Internet-enabled mode must be the default-available option and chosen immediately for any OOB/osint challenge. The target-only default cost us real money on runs that could never win.**
3. **gpt-5.3-codex: $4.06 across the hard tier for 0 solves** (it only landed TrustPath once handed internet, under the GPT-open label). Spent like a capable model, delivered nothing where it mattered. **→ Fine for easy/web with internet; do not pour budget into it on hard pwn/crypto.**

### What was efficient (do more of this)
Haiku (4 solves / $0.08), DeepSeek-Pro (4 / $7), and internet-GPT (TrustPath / $0.07). And note: the **content-filtered** models (Opus, GPT-6-sol) wasted *attempts and time* but barely any *money* — they bail in ~5 seconds. The money hemorrhage was the expensive-model-on-unwinnable-challenge pattern, not the filter.

---

## 1. What solved each challenge (12/16)

| id | challenge | diff | category | solved by |
|----|-----------|------|----------|-----------|
| 79390 | DNS Dossier | easy | web | Haiku 5.5 |
| 79456 | procrastinator | easy | crypto | Haiku 5.5 |
| 79455 | ThreeKeys | medium | forensics | Haiku 5.5 |
| 79461 | Ticket to Mars | medium | osint | Haiku 5.5 |
| 79460 | Predictable | hard | web | DeepSeek-v4-pro |
| 79463 | Dash Rush | insane | web | DeepSeek-v4-pro |
| 79473 | Controlled Meltdown | insane | — | DeepSeek-v4-pro |
| 79476 | phase phantom | insane | — | DeepSeek-v4-pro |
| 79474 | Hardware Managing System | insane | — | Sonnet 5.5 |
| 79475 | GHZ Collapse | insane | — | Sonnet 5.5 |
| 79459 | TrustPath | medium | web | gpt-5.3-codex **+ internet** |
| 79457 | twisted cloud | hard | crypto | **gpt-6-luna** |

**Still unsolved (4) — the rarest on the board:** Silent Stream (hard pwn, 6 team-solves), Shard Council (insane, 4), Perimeter Zero (hard pwn, **3** — the single hardest), Ridiculed (hard osint, 9).

---

## 2. The big findings

### 2a. Claude and the newer GPT models are CONTENT-FILTERED on exploit challenges — this was the #1 blocker
- **Sonnet 5.5, Opus 5.5, gpt-6-sol, gpt-6.1-sol** all hit a *cybersecurity content filter* on exploit/crypto challenges. They engage one step, then the model's output is blocked and the attempt dies fast and cheap (~5s, <$0.02).
- **Evidence (from traces):** Opus → `finish_reason: "content_filter"` (empty output). gpt-6.1-sol → explicit `litellm.ContentPolicyViolationError: "This content was flagged for possible cybersecurity risk."` on the **first** call.
- **Models that do NOT filter (engage fully):** `deepseek-v4-pro`, `deepseek-v4-flash`, `gpt-5.3-codex`, `gpt-6-luna`.
- **Pattern: newer / more "safety-aligned" = more filtered.** Newer is NOT better for offensive security work.
- **Nuance:** Sonnet still solved the *non-exploit* insane challenges (GHZ Collapse, Hardware Managing System) — the filter triggers on exploit/crypto content specifically, not everything.
- **→ Rule of thumb: for exploit/pwn/crypto, use DeepSeek or gpt-5.3-codex / gpt-6-luna. Reserve Claude for forensics/osint/misc where there's no exploit payload.**

### 2b. Our sandbox blocks the internet by design — and some challenges REQUIRE internet
- The solver runs network-isolated (reaches only the challenge target) as a safety control. That blocks whole categories:
  - **TrustPath** (X.509 cert-trust) needs an out-of-band callback → impossible in the sandbox. Enabling internet solved it **in 44s, by the agent itself** (so it counts for the agent, not a manual human solve).
  - **OSINT (Ridiculed)** needs the open internet to research → all 7 sandboxed attempts failed. (With internet, luna still timed out at 30 min — osint is hard — but internet is *necessary*.)
- The fix is a built-in config option: **`remote_network: "open"`** gives the solver real internet egress and reaches the real remote target directly (no forwarder). We also taught the scope tripwire to allow it (`scope.py` returns no violations when `"*"` is in `allowed_hosts`; `htb_challenges.py` adds `"*"` in open mode). Default/graded runs keep full isolation.
- **→ Have an internet-enabled config ready and use it for OOB/callback/osint challenges from the start.**

### 2c. Winning models go DEEP; losing ones flail at the surface (the twisted cloud lesson)
- twisted cloud's vuln was a **predictable PRNG (Mersenne Twister / MT19937)**.
  - **gpt-6-luna solved it (14 steps, 130s):** read the PHP source → recognised the RNG was predictable → **wrote a C + OpenMP brute-forcer to recover the seed (284807333)** → **reimplemented MT19937 in Python to predict the secret value** → logged in → flag.
  - **gpt-5.3-codex failed (27 steps, gave up):** it understood there was a "leak" but **never left the HTTP / password-guessing layer**, and quit with *"No further progress possible under constraints."*
- **→ The decisive move is dropping to low-level offline compute (write C, brute-force seeds, reimplement the crypto) instead of poking the web app. Favour models (and prompting) that do this.**

### 2d. Over-parallelism causes infrastructure errors
- Running **8 solvers at once** → Docker/container `infrastructure_error`s (resource contention on one laptop).
- Dropping to **2–3 parallel** fixed it cleanly. HTB's own container spawner is fine (verified: a container spawns in ~4s on demand).

### 2e. Network stability matters — a flaky connection looks exactly like a model bug
- While the laptop's VPN/WiFi was unstable (user walking around), gateway calls returned transient **HTTP 400s** that *looked* like model incompatibility.
- The models were fine on a stable connection (verified by replaying the exact payload). **→ Keep VPN + WiFi steady during runs; a dropped request → a 400, not a model failure.**

---

## 3. Model behaviour reference (Duke gateway)

| model | filtered on exploits? | engages? | cost | notes |
|-------|----------------------|----------|------|-------|
| Haiku 5.5 | no | yes | cheapest | solved the easy/medium ones fast |
| Sonnet 5.5 | **yes (exploit)** | partial | mid | solved non-exploit insanes |
| Opus 5.5 | **yes** | no (bails ~5s) | high | content_filter; no better than Sonnet here |
| deepseek-v4-pro | no | yes | low | workhorse — 4 solves |
| deepseek-v4-flash | no | yes | **cheapest** | hits *time* not cost → good for long grinds |
| gpt-5.3-codex | no | yes | mid | strong coder; solved TrustPath w/ internet |
| gpt-6-sol | **yes (after rounds)** | starts then blocks | mid | content-filter once exploit content builds up |
| gpt-6-luna | no | yes | mid | **strongest unfiltered GPT** — solved twisted cloud |
| gpt-6.1-sol | **yes (instant)** | no | — | explicit ContentPolicyViolationError on call 1 |
| gpt-5.4-pro | — | — | — | returned EMPTY on probe → unusable |

Cost behaviour: Opus/GPT hit the **per-attempt $ cap** (`max_cost_usd`) *before* 30 min → `budget_exhausted`. Flash is so cheap it hits the **time** limit → `timeout`. So "give it more time" only helps the cheap models.

---

## 4. MISTAKES WE MADE (Paul: read this)

1. **Started the sandbox fully internet-isolated** → silently blocked every challenge needing an OOB callback or osint research (TrustPath, Ridiculed). *Fix: build an internet-enabled mode and use it when the challenge needs it.*
2. **Over-parallelised (8-way)** → `infrastructure_error`s and wasted attempts/budget. *Fix: 2–3 solvers at a time.*
3. **Threw Claude / GPT-6-sol at exploit challenges** → content-filtered, burned time and money for nothing. *Fix: DeepSeek / gpt-5.3-codex / gpt-6-luna for exploit/crypto/pwn.*
4. **Ran everything at temperature 0** (deterministic) → re-runs retraced the *exact same* failed path. *Fix: vary temperature (0.7 for diversity, or multiple trials) for a genuinely fresh attempt; low temp (0.1) when you want a focused deep dive.*
5. **A self-imposed 30-min per-attempt cap** that was too short for hard challenges — and it is **our rule (`wall_clock_s`), not the competition's.** HTB has NO per-challenge time limit (grind until the event ends). *Fix: extend time for hard challenges, especially cheap models like flash.*
6. **(Assistant) diagnosed failures wrong before reading the actual error** — blamed HTB's spawner, then "model incompatibility," when the real causes were network flakiness and the content filter. *Fix: open the trace and read the real error (`llm_error`, `finish_reason`, `stop_reason`) before concluding anything.*
7. **`handoff_notes` only fed the single newest note and skipped fast give-ups** → limited cross-attempt learning. *Fixed:* now feeds up to 3 past notes (newest first, tagged with the model), and deliberately **skips any note that mentions the content filter** (telling the agent it was filtered risks it self-censoring, with no upside).

---

## 5. Scoring & strategy

- **Dynamic scoring:** a challenge's points decay as more teams solve it (tryout DNS Dossier = `900 − 25·solves`); all current solvers share the current value, so **first blood is a stat + a tie-break, not bonus points.** Your rank slips as others solve even if you hold your solves.
- **Target with the solve distribution.** The standout was twisted cloud — 12 team-solves, the *same* popularity as insanes we'd already solved — i.e. winnable and we were inexplicably missing it. Targeting it first is what got luna to crack it. There was **no** commonly-solved challenge we were missing besides that.
- **Compete marks max at 5+ solves** (we're at 12). Placement bonus +15/+10/+5 for top 3.
- **Agent-team vs human-team (UNRESOLVED — ASK PROF MIKE):** each MCP token is its own `[AI] ai-agent-of-<user>` scoreboard row. Solves do **not** pool across Jack's and Paul's agents, nor into the human team **Kali_Yu_Nai** (id 339976, country TH, 0 pts). Confirm which row the class actually grades and whether two agents can count as one team.

---

## 6. How to run it (reference)

- Configs live in `configs/`: `agent-htb.json` (Haiku, auto-climb OFF), `-sonnet`, `-deepseek` (pro), `-flash`, `-gpt` (gpt-5.3-codex), `-gpt6` (gpt-6-sol), `-luna` (gpt-6-luna), `-opus`, and the **internet** variants `-open` (gpt-5.3-codex), `-open-luna`, `-open-flash`.
- Run: `python scripts/race_htb.py --assign <ids...> --config configs/<cfg>.json --out runs/race --max-parallel 2 [--trials N]`. `--all --skip-solved` runs everything unsolved; `--watch` waits for the challenge drop.
- **Internet mode:** set `"remote_network": "open"` in the config's `environment`. The solver then has egress and reaches the real target directly; the scope tripwire is auto-disabled in open mode.
- **Time/cost knobs:** per-config `limits.wall_clock_s` (default 1800 = OUR rule), `limits.max_cost_usd` (per-attempt $ cap), `limits.max_steps`. `--laptop-budget` and the gateway's server-side `$25` cap bound total spend.
- **Live dashboard:** `python scripts/dashboard.py --port 8793` → `scripts/dashboard.html`. Badges all 8 models, live spend (real via `/key/info` when readable, else token estimate), and the leaderboard. Reads `runs/race*` + `runs/htb-test`.
- **handoff_notes** is ON: `Controller.prior_notes` feeds up to 3 prior attempts' notes (cross-model) into each new attempt; notes are written on `budget_exhausted`/`timeout`/`wrong_flag`.

---

## 7. Next-session plan (own API key)

- The team $25 gateway key is nearly tapped out. Plan: continue on Jack's own Claude budget (~$100/mo Max, unused this month — allowed by the rules).
- **Two caveats before relying on it:**
  1. **Claude is content-filtered on exploit challenges** (see §2a), so a Claude key only helps the *non-exploit* ones. The 3 remaining (2 pwn + 1 insane) are exactly where Claude filters — it likely won't move them. Ridiculed (osint) + internet is the better Claude target.
  2. **Integration isn't drop-in.** The solver's `GatewayClient` speaks the OpenAI chat-completions format (what the Duke gateway serves). Anthropic's own API uses the **Messages API** (different request/response shape). To use a raw Anthropic key you'd need either a small client adapter in `ctfagent/llm.py` or an OpenAI-compatible proxy in front of it. Also verify the $100 Max subscription value is actually usable as raw **API** credits (console.anthropic.com), which is separate from the claude.ai subscription.
- **Where to spend next effort:** Ridiculed (osint) deserves a longer internet run (bump `wall_clock_s` to 3600 on an open config). The pwns (Perimeter Zero, Silent Stream) want a strong unfiltered coder — `gpt-5.3-codex`, `gpt-6-luna`, or an untried one (`qwen3-coder`, `glm-5`, `kimi-k2.5`) — with internet to pull tools like pwntools, and plenty of time.
