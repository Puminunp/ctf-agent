#!/usr/bin/env python
"""One tool-call cycle against the gateway for a given model. Costs a few hundred tokens.

    $env:LITELLM_TOKEN = "<your key>"
    .venv\\Scripts\\python.exe scripts/check_toolcall.py --model claude-haiku-5-5

Passes when the model (1) answers the first request with a run_shell call and (2) accepts the tool
result and replies. Prints token usage, which is the first estimate of cost per step.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctfagent.llm import GatewayClient, LLMError  # noqa: E402
from ctfagent.tools import TOOL_SPECS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help='exact ID, for example "GPT 4.1" or claude-haiku-5-5')
    ap.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", "https://litellm.oit.duke.edu/v1"))
    args = ap.parse_args()
    token = os.environ.get("LITELLM_TOKEN")
    if not token:
        sys.exit("set LITELLM_TOKEN first")

    client = GatewayClient(args.base_url, token, args.model, temperature=0.0, timeout_s=60, retries=1)
    messages = [
        {"role": "system", "content": "You are a test agent. Use the tools."},
        {"role": "user", "content": "Run the shell command `echo cycle-ok` and tell me what it printed."},
    ]
    total_in = total_out = 0
    try:
        r1 = client.complete(messages, TOOL_SPECS)
        total_in += r1.input_tokens or 0
        total_out += r1.output_tokens or 0
        if not r1.tool_calls:
            sys.exit(f"FAIL: no tool call returned (finish_reason={r1.finish_reason}); content={r1.content!r}")
        call = r1.tool_calls[0]
        print(f"step 1 ok: model called {call.name} {call.arguments_raw}")
        messages.append(r1.assistant_message)
        messages.append({"role": "tool", "tool_call_id": call.id, "content": "exit_code: 0\ncycle-ok"})
        r2 = client.complete(messages, TOOL_SPECS)
        total_in += r2.input_tokens or 0
        total_out += r2.output_tokens or 0
        print(f"step 2 ok: model replied {r2.content!r} (tool calls: {len(r2.tool_calls)})")
        print(f"usage reported: input={r1.input_tokens}+{r2.input_tokens} output={r1.output_tokens}+{r2.output_tokens}")
        print("PASS: one full tool-call cycle works with this model")
    except LLMError as e:
        sys.exit(f"FAIL: {e}")


if __name__ == "__main__":
    main()
