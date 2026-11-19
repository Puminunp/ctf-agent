# Ridiculed — executor plan v2 (synthesis: my trace analysis + 2 independent DeepSeek plans)

> Injected as the newest handoff note. Assumes `ridiculed-report.md` facts are known. Goal: crack the AS-REP **correctly**, use `aduser1`'s credential against `154.57.164.73:41314` (and/or the LDAP directory), get `HTB{...}`.

## HARD RULES (do not break)
- **Never consult write-ups, solutions, or leaked flags.** This is a scored challenge; solve it from the artifacts only. (Ignore any suggestion to "search GitHub for the writeup" — forbidden.)
- **No candidate password is a hit** until its decrypted plaintext contains BOTH ASCII `FORENPACK` and `krbtgt`. The 4-byte tag check alone is a false-positive generator (it produced the bogus `kgdrr`). Tag check = fast pre-filter only.
- **No pure-Python crack over >10k candidates.** Use a real engine (hashcat/JtR) or a C loop.
- **No `sleep;cat` poll loops.** Background the crack with `setsid nohup`, write a sentinel, check ≤3 times total.
- **Do not "repair" the 4 truncated edata bytes** (RC4 stream cipher; leading plaintext decrypts fine). If a tool rejects the length, pad edata with `00`×4 to the declared 260.

## 1. CORRECTNESS GATE — settle the crypto before spending CPU
1. `pip install --user impacket pycryptodome py7zr ldap3` (one call).
2. The prior extraction is structurally sound: AS-REP `enc-part` **etype 23 (RC4) at offset 1262 is the roast target** (user key); the **etype-18 blob at offset 144 is the TICKET enc-part, encrypted with the krbtgt key — NOT user-crackable. Do not attempt to crack it (ignore any "-m 19900 on etype-18" idea; there is only ONE user-encrypted enc-part and it is the etype-23 one).**
3. **Do not guess key usage (3 vs 8).** Use a tool that hardcodes it: hashcat `-m 18200`, John `--format=krb5asrep`, or impacket `KeyUsage.AS_REP_ENC_PART`. If one of these also fails on a word you *know* is right, the problem is the wordlist, not the constants.
4. Build the validator once: `plain = RC4(HMAC-MD5(MD4(utf16le(pw)), usage), edata)` → require `b"FORENPACK" in plain and b"krbtgt" in plain`. Use it to confirm the final password against the raw pcap bytes regardless of which engine found it.

## 2. CRACKER — real engine in userspace (no root, internet OK), in order
1. **Static hashcat:** `curl -L` the `hashcat-6.2.6.7z` from the GitHub release, `python -m py7zr x` it, run `./hashcat.bin -m 18200 asrep.hash <wordlist> -r rules/best64.rule --potfile-path /tmp/pot --outfile /tmp/HIT`. Add `--force -D 1` if it complains about the CPU/OpenCL backend.
2. **If hashcat needs OpenCL and it's missing (common in containers): John jumbo.** `git clone --depth 1 https://github.com/openwall/john && cd john/src && ./configure --disable-opencl && make -sj2` (no root, ~2–3 min), then `./john --format=krb5asrep --wordlist=... asrep.hash`. JtR krb5asrep hardcodes the AS-REP usage.
3. **Last resort:** a ~50-line C cracker (MD4→HMAC-MD5(usage 8)→HMAC-MD5(checksum)→RC4 first ~64 bytes→`strstr("FORENPACK")`) compiled with `gcc -O3` → ~10⁶–10⁷/s/core. Or `multiprocessing` over `Crypto.Hash.MD4`/`ARC4` (C-backed) — far faster than hand-rolled Python.

## 3. WORDLISTS — best yield per minute, stop at first validated hit
1. **Themed seed list FIRST** (generate ~a few thousand, run in seconds): `forenpack/Forenpack/ForenPack/FORENPACK`, `ridiculed/Ridiculed`, `aduser1`, `WIN-FLV7AUKV7S3`, `Duke/DukeAI/HTB/ctf`, + seasons/years `2018–2026`, + suffixes `! @ # $ 1 123 1234 2024! 2025!`, + leet (`f0r3np4ck`, `@dus3r1`). The flavor word "ridiculed" may hint a jokey/taunting password — try meme/taunt words. HTB passwords usually live here.
2. **rockyou + `best64.rule`**, then **`dive.rule` / `OneRuleToRuleThemAll`**.
3. **weakpass_3a** (download). Avoid full rockyou2021 (too big to materialize).
4. **Hybrid masks around the theme:** `-a 6 forenpack.txt ?d?d?d?d` and `...?d?d?d?d!`, lowercase variants.

## 4. BUDGET DISCIPLINE — one detached job, ≤3 checks
```
setsid nohup bash -c './hashcat.bin -m 18200 --potfile-path=/tmp/pot --outfile=/tmp/HIT asrep.hash rockyou.txt -r rules/best64.rule --quiet; touch /tmp/DONE' >/tmp/crack.log 2>&1 &
```
The 120 s shell cap kills the shell, **not** the `setsid` child — the crack runs to completion. While it runs, do other useful work (§5 fingerprint, build the themed list, prep the LDAP client). Then check ONCE: `[ -f /tmp/DONE ] && cat /tmp/HIT || tail -1 /tmp/crack.log`. ≤3 checks per job. Batch all `pip install`s / downloads into single calls.

## 5. ENDGAME — the capture is LDAP-heavy, so LDAP is the likely flag source
Once you have `aduser1:<pw>` (validated), in priority order:
1. **LDAP simple bind + search (HIGHEST probability).** `ldap3` or `impacket-ldap` → bind `aduser1@AD.FORENPACK.HTB:<pw>` on `ldap://154.57.164.73:41314`, base `dc=ad,dc=forenpack,dc=htb`; **search for the flag in attributes** (`description`, `info`, `comment`), and for any object named like `flag`. The 246 LDAP packets strongly suggest the secret lives in the directory.
2. **The silent `:41314` as a line dialogue (ONE session, not one-shot probes):** connect, wait 10–20 s for a slow banner, then send `aduser1\n`, read, send `<pw>\n`, read. Also try `aduser1:<pw>\n`, `AUTH/LOGIN aduser1 <pw>\n`, a JSON cred line, and `shutdown(SHUT_WR)` after sending. Do the whole matrix in one scripted call.
3. **HTTP(S) basic auth:** `curl -v --max-time 5 -u aduser1:<pw> http(s)://154.57.164.73:41314/` and `/flag /login /admin`; silent-then-200 behind a proxy is common.
4. **SMB/Kerberos with explicit port:** `impacket-smbclient -port 41314 ad.forenpack.htb/aduser1:<pw>@154.57.164.73`; `impacket-getTGT 'AD.FORENPACK.HTB/aduser1:<pw>'` then `-k` clients.
Submit whatever `HTB{...}` appears; never guess a flag.

## 6. FALLBACK if the service stays silent or the flag is "what they stole"
Once you have the password you also have `aduser1`'s key → decrypt the AS-REP `enc-part` → recover the **EncASRepPart session key**; if any TGS-REP exists in the pcap, chain to the LDAP service session key and **unwrap the GSS-SPNEGO-sealed LDAP** — the stolen secret may be inside that traffic. Ignore the 2-packet SMB (nothing) and treat the `github.com` string as a red herring unless everything else is exhausted.

## 7. EXECUTION ORDER (fits ~30–60 min)
1. pip installs + download/extract hashcat (1 call). 2. Confirm hash vs hashcat `-m 18200` / build validator (1). 3. Themed seed list → quick crack (1). 4. Launch detached rockyou+best64 → sentinel (1). 5. While it runs: fingerprint `:41314` + prep the LDAP client (2). 6. Check `/tmp/DONE` once → on hit, validate → §5 LDAP-bind endgame (1–3). 7. No hit → weakpass/dive detached; meanwhile prep §6 session-key decrypt. 8. On credential → LDAP search is the top flag bet.
