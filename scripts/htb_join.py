#!/usr/bin/env python
"""Register this player's HTB agent team for a CTF event. Run it once per player, by hand.

An MCP token acts as its own HTB identity ("ai-agent-of-<you>") with its own team, and that team has
to join the event before the agent can read challenges or submit flags.

    python scripts/htb_join.py            # asks for the event password, hidden
    python scripts/htb_join.py --check    # only shows whether the agent team is already in

The password is typed by a person at the prompt (or set as HTB_EVENT_PASSWORD in .env). It is sent to
HTB and nowhere else: not printed, not logged, not stored by this script.
"""

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctfagent.envfile import load_env_file  # noqa: E402
from ctfagent.htb import DEFAULT_URL, HtbError, McpClient  # noqa: E402

_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[A-Za-z~]|\x1b.|[\x00-\x1f\x7f]")


def clean_typed(text: str) -> str:
    """Remove terminal escape codes that a paste into a hidden prompt can leave behind."""
    return _ESCAPES.sub("", text).strip()


def event_row(client: McpClient, ctf_id: int) -> dict:
    for e in client.call_tool("list_ctf_events") or []:
        if e.get("id") == ctf_id:
            return e
    raise HtbError(f"event {ctf_id} is not in the list HTB returned")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ctf-id", type=int, default=int(os.environ.get("HTB_CTF_ID", "3755")))
    ap.add_argument("--check", action="store_true", help="show the status and stop")
    args = ap.parse_args()

    load_env_file(ROOT / ".env")
    token = os.environ.get("HTB_MCP_TOKEN")
    if not token:
        sys.exit("HTB_MCP_TOKEN is not set. Put it in .env (see README).")
    client = McpClient(os.environ.get("HTB_MCP_URL", DEFAULT_URL), token)

    try:
        teams = client.call_tool("retrieve_my_teams") or []
        if not teams:
            sys.exit("this token has no team on HTB")
        team = next((t for t in teams if t.get("isCaptain")), teams[0])
        event = event_row(client, args.ctf_id)
        print(f"Agent team : {team['name']} (id {team['id']})")
        print(f"Event      : {event['name']} (id {event['id']}, {event.get('status')})")
        print(f"Joined     : {bool(event.get('hasJoined'))}   can play: {bool(event.get('canPlay'))}")
        if event.get("hasJoined") or event.get("canPlay"):
            print("Already in. Nothing to do.")
            return
        if args.check:
            return

        print("\nThis registers the agent team for the event and sends the consent flag HTB asks for.")
        password = os.environ.get("HTB_EVENT_PASSWORD") or ""
        if not password and event.get("hasCode"):
            password = getpass.getpass("Event password (hidden, then Enter): ")
        password = clean_typed(password)
        if event.get("hasCode") and not password:
            sys.exit("no password entered; nothing was sent")
        if password:
            print(f"Received {len(password)} characters.")   # the count only, to catch a typo or a bad paste

        call = {"ctf_id": args.ctf_id, "team_id": team["id"], "consent": True}
        if password:
            call["ctf_password"] = password
        answer = client.call_tool("join_ctf_event", call)
        text = str(answer)
        if password:
            text = text.replace(password, "[password]")
        print("HTB answered:", text[:400])

        event = event_row(client, args.ctf_id)
        print(f"Joined now : {bool(event.get('hasJoined'))}   can play: {bool(event.get('canPlay'))}")
    except HtbError as e:
        sys.exit(f"HTB error: {e}")


if __name__ == "__main__":
    main()
