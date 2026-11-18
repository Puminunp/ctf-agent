"""Model-escalation ladder: solve a challenge on the cheapest model first, step up only on failure.

This is the cost-optimisation policy for the live event. Haiku is ~40x cheaper than Opus, so every
challenge is probed with Haiku first; a stronger model is tried only when the cheaper one failed for a
reason a stronger model could plausibly fix (it engaged but could not close it), never on a timer, and
only when the remaining laptop budget can fully fund the pricier attempt.

The run script owns the clock, the budget and Docker; this module only decides which rung to try next
and when to stop, so it is pure and unit-testable without a gateway or a container.
"""

from __future__ import annotations

from .config import Config, Escalation


def plan_rungs(escalation: Escalation, difficulty: str) -> list[int]:
    """Indices into ``escalation.ladder`` to try, cheapest first.

    Empty when no ladder is configured (the caller then runs the single base model). ``difficulty`` may
    bump the starting rung up (e.g. skip Haiku on an "insane" challenge) via start_rung_by_difficulty.
    """
    if not escalation.ladder:
        return []
    start = escalation.start_rung_by_difficulty.get((difficulty or "").lower(), 0)
    start = max(0, min(int(start), len(escalation.ladder) - 1))
    return list(range(start, len(escalation.ladder)))


def run_challenge_ladder(cfg: Config, cid, trial, *, difficulty, spent_fn, laptop_budget,
                         recorded, run_rung, log=print):
    """Drive one challenge up the ladder, calling ``run_rung(rung_cfg)`` for each attempt.

    ``run_rung`` runs one attempt with the given per-rung config and returns its results record (a dict
    with at least ``verified`` and ``status``). ``spent_fn()`` returns dollars already spent on this
    laptop; ``recorded`` is the set of run_ids already finished in a previous process (so a resumed run
    skips rungs it has done). Returns the final record it produced, or None if nothing ran.

    Stop conditions, in order: the flag verified; an infrastructure error (a bigger model will not fix
    the gateway); a status outside ``escalate_on`` (e.g. a scope violation); the ladder is exhausted;
    or the remaining budget cannot fully fund the next rung's per-attempt cap (plus any reserve).
    """
    esc = cfg.escalation
    indices = plan_rungs(esc, difficulty)
    rungs = ([(cfg.with_rung(esc.ladder[i]), esc.ladder[i].max_cost_usd) for i in indices]
             if indices else [(cfg, cfg.limits.max_cost_usd)])

    last = None
    for pos, (rung_cfg, cap) in enumerate(rungs):
        run_id = f"{rung_cfg.config_id}-{cid}-t{trial}"
        if run_id in recorded:
            log(f"skip {run_id}: already recorded")
            continue
        remaining = laptop_budget - spent_fn()
        if remaining <= 0:
            log(f"budget stop: nothing left for {run_id}")
            return last
        headroom = cap + (esc.reserve_usd if pos > 0 else 0.0)
        if cap and remaining < headroom:
            log(f"skip {rung_cfg.model}: ${remaining:.2f} left < needed ${headroom:.2f}")
            break

        last = run_rung(rung_cfg)
        if last.get("verified"):
            return last
        status = last.get("status")
        if status == "infrastructure_error":
            log("infrastructure error; not escalating")
            return last
        if status not in esc.escalate_on:
            log(f"status '{status}' is terminal for this challenge; not escalating")
            return last
    return last
