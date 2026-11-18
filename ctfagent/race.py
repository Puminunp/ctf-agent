"""Ranking and team-splitting for the live race — pure functions, no network, so they unit-test offline.

First blood in this event gives no bonus points (static scoring: every solver gets the challenge's full
points). Speed still decides placement, because HTB breaks ties by who reached a score first. So the
race goal is: start the fastest-to-solve challenges first, and split the set with Paul so we are not both
racing the same one.

`rank_challenges` orders easiest/fastest-to-blood first. `split_challenges` reserves the N easiest for us
(we start before Paul), then deals the rest out so the split is even, to a target size for our side.
"""

from __future__ import annotations

# Lower = attempt earlier. "" (unknown label) sits with medium.
DIFFICULTY_ORDER = {"very easy": 0, "easy": 1, "medium": 2, "hard": 3, "insane": 4, "": 2}

# How fast the agent tends to reach first blood by category (lower = faster). Matched by substring on
# the category name, so "Web", "web exploitation" etc. all hit "web". Unknown categories sit in the middle.
CATEGORY_SPEED = {
    "web": 0, "osint": 1, "misc": 2, "coding": 2, "forensic": 2, "crypto": 3,
    "ai": 3, "ml": 3, "cloud": 4, "mobile": 4, "android": 4, "ios": 4,
    "reversing": 5, "rev": 5, "pwn": 6, "binary": 6, "hardware": 7, "blockchain": 7,
}
_UNKNOWN_CATEGORY_SPEED = 5


def _category_speed(ch: dict, cat_names: dict | None) -> int:
    name = ((cat_names or {}).get(ch.get("challenge_category_id")) or "").strip().lower()
    for key, rank in CATEGORY_SPEED.items():
        if key in name:
            return rank
    return _UNKNOWN_CATEGORY_SPEED


def difficulty_rank(ch: dict) -> int:
    return DIFFICULTY_ORDER.get(str(ch.get("difficulty", "")).strip().lower(), 2)


def rank_key(ch: dict, cat_names: dict | None = None) -> tuple:
    """Sort key: coarse difficulty label, then points (a finer proxy for difficulty when the label is
    just 'medium'/'hard'), then category speed, then id for a stable order."""
    return (difficulty_rank(ch), int(ch.get("points") or 0), _category_speed(ch, cat_names), int(ch.get("id") or 0))


def rank_challenges(challenges: list[dict], cat_names: dict | None = None) -> list[dict]:
    """Easiest / fastest-to-blood first."""
    return sorted(challenges, key=lambda c: rank_key(c, cat_names))


def split_challenges(challenges: list[dict], ours: int = 5, easiest_to_us: int = 2,
                     cat_names: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Return (our_set, pauls_set).

    We start before Paul, so the `easiest_to_us` easiest go to us for quick first bloods. The rest are
    dealt out alternately (us first) until our side reaches `ours`; everything left is Paul's. Both lists
    stay in easiest-first order. With 10 challenges and the defaults this is a 5/5 split whose 2 easiest
    are ours.
    """
    ranked = rank_challenges(challenges, cat_names)
    ours = max(0, min(ours, len(ranked)))
    easiest_to_us = max(0, min(easiest_to_us, ours))
    us = ranked[:easiest_to_us]
    paul: list[dict] = []
    for i, ch in enumerate(ranked[easiest_to_us:]):
        if len(us) < ours and i % 2 == 0:
            us.append(ch)
        else:
            paul.append(ch)
    while len(us) < ours and paul:            # odd leftovers: keep filling our side first
        us.append(paul.pop(0))
    return us, paul


def fmt(ch: dict, cat_names: dict | None = None) -> str:
    cat = (cat_names or {}).get(ch.get("challenge_category_id"), str(ch.get("challenge_category_id")))
    return (f"  [{ch.get('id')}] {str(ch.get('difficulty', '?')):<9} {str(cat):<10} "
            f"{int(ch.get('points') or 0):>4}pts  {ch.get('name')}")
