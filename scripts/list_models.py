#!/usr/bin/env python
"""List model IDs the Duke AI Gateway allows for your key (stand-in for the instructor's list_gateway_models.py).

Needs LITELLM_TOKEN in the environment. LITELLM_BASE_URL defaults to https://litellm.oit.duke.edu/v1.
Model IDs can contain spaces (for example "GPT 4.1"); copy them exactly into configs/agent.json.
A listed model is not proof of tool-call support or quota: the first pilot attempt is that check.
"""

import json
import os
import sys
import urllib.error
import urllib.request

base = os.environ.get("LITELLM_BASE_URL", "https://litellm.oit.duke.edu/v1").rstrip("/")
token = os.environ.get("LITELLM_TOKEN")
if not token:
    sys.exit("set LITELLM_TOKEN first")
req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {token}"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
except urllib.error.HTTPError as e:
    sys.exit(f"gateway returned HTTP {e.code}")
except (urllib.error.URLError, OSError) as e:
    sys.exit(f"could not reach the gateway ({type(e).__name__}); check VPN/network")
for model_id in sorted(m["id"] for m in data.get("data", [])):
    print(model_id)
