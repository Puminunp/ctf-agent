#!/usr/bin/env python
"""Put a secret from the clipboard into .env, without it ever showing in the terminal or in chat.

    1. Copy the secret to the clipboard (e.g. your Duke gateway key).
    2. python scripts/set_env_secret.py LITELLM_TOKEN

Reads the clipboard (pbpaste), writes NAME=<secret> into .env (replacing any existing line, keeping the
rest), sets .env to mode 600, clears the clipboard, and prints only the length of what it stored.
The value is never printed. Reuse it for the prof's competition key later (same command).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def main() -> None:
    args = sys.argv[1:]
    prompt = "--prompt" in args
    names = [a for a in args if not a.startswith("-")]
    if len(names) != 1 or not names[0].isidentifier():
        sys.exit("usage: set_env_secret.py ENV_VAR_NAME [--prompt]   (e.g. LITELLM_TOKEN)")
    name = names[0]
    if prompt:
        import getpass
        secret = getpass.getpass(f"Paste the {name} value and press Enter (input stays hidden): ")
    else:
        try:
            secret = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            sys.exit(f"could not read the clipboard: {e}")
    secret = secret.strip()
    if not secret:
        sys.exit("no value provided — re-run and paste the key.")
    if any(c.isspace() for c in secret):
        sys.exit("the value has whitespace inside it — that does not look like a key; aborting.")

    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, replaced = [], False
    for ln in lines:
        if ln.split("=", 1)[0].strip() == name:
            out.append(f"{name}={secret}")
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(f"{name}={secret}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(ENV, 0o600)

    try:  # clear the clipboard so the secret does not linger
        subprocess.run(["pbcopy"], input="", text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pass
    print(f"stored {name} in .env ({'replaced' if replaced else 'added'}, len {len(secret)}); clipboard cleared.")


if __name__ == "__main__":
    main()
