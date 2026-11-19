# Ridiculed — full intelligence report (for creative planning)

**Challenge:** `Ridiculed` · category **osint** (really AD / network forensics) · HTB "Duke AI CTF" (event 3755)
**Status:** UNSOLVED. 9 team-solves on the board (one of the rarer ones). Our autonomous agent (Opus 4.8, internet enabled) got deep over 65 steps but hit its $10 cost cap before solving.
**Flag format:** `HTB{...}`

> Purpose of this doc: hand it to a fresh expert planner. Everything below is **verified from the agent's own run trace**, with the open questions and likely mistakes called out explicitly. The goal is a *more creative, concrete* plan than "just run a bigger wordlist."

---

## 1. The prompt we are given

> "We know that a malicious actor ran a pretty noisy tool inside the network. Given the captured network traffic, find out what they stole and how it can be used!"

- **File provided:** a zip containing a single **`capture.pcap`** (273 packets, ~330 KB).
- **Target service:** `154.57.164.73:41314` (TCP). Accepts connections but returns **nothing** to blind probes (empty line, `help`, `HELP`, `GET /`, raw wait, TLS `s_client` all returned nothing).
- Interpretation of the prompt: *"noisy tool"* = a known offensive AD tool run on the wire (the capture looks exactly like an **AS-REP roast**, e.g. Rubeus / Impacket `GetNPUsers` / kerbrute). *"what they stole"* = a roastable credential. *"how it can be used"* = crack it → authenticate to the target service → flag.

---

## 2. The network capture — established facts

- **Two hosts:** `192.168.56.105` (client/attacker) ↔ `192.168.56.104` (Domain Controller). Also `.1` and `.255` (gateway/broadcast). No external IPs in the actual packets.
- **Domain:** `ad.forenpack.htb` (realm **`AD.FORENPACK.HTB`**). DC hostname **`WIN-FLV7AUKV7S3`**.
- **Protocol breakdown (by packet count):** TCP/389 LDAP ×246, UDP/53 DNS ×12, TCP/88 Kerberos ×12, TCP/445 SMB ×2, UDP/57621 ×1.
- **DNS:** a flurry of SRV/A lookups for `_ldap._tcp...ad.forenpack.htb` and the DC host. **`github.com` appears** in the capture as a string, but there is **no TCP session to github** — earlier notes flagged it as a likely connectivity-check / red herring. (Worth re-checking whether it's meaningful, but low priority.)
- **LDAP (389):** cleartext **rootDSE** query, then a **GSS-SPNEGO sealed** bind and encrypted traffic. The sealing is **Kerberos, not NTLM** — the string `NTLMSSP` appears **0 times** in the capture, so the LDAP payloads can't be NTLM-decrypted. The sealed LDAP is effectively opaque without the session key.
- **SMB (445):** only 2 packets, 1 byte of payload — nothing.

---

## 3. The crown jewel — the AS-REP roast (this is "what they stole")

The Kerberos exchange (packets 258–265) is an **AS-REQ / AS-REP for `aduser1@AD.FORENPACK.HTB`**:

- **AS-REQ (pkt 263)** has **no pre-authentication** (only `PA-PAC-REQUEST`) → the account is **AS-REP-roastable** ("Do not require Kerberos preauthentication" set).
- The **AS-REQ requested only etype 23 (RC4)** — the decoded etype list is `SEQUENCE { INTEGER 0x17 }`. So the client forced RC4.
- The **AS-REP (pkt 264)** contains two encrypted blobs in the reassembled server→client Kerberos blob (1536 bytes, DER declares 1540):
  - **etype 18 (AES256)** at offset 144 — this is the **ticket's** enc-part (encrypted with the **krbtgt** key → *not* crackable from a user password; ignore it).
  - **etype 23 (RC4)** at offset 1262 (the **last** structure) — this is the **AS-REP enc-part**, encrypted with **aduser1's** long-term key → **this is the roast target.**

### The extracted hash

```
$krb5asrep$23$aduser1@AD.FORENPACK.HTB:983ca6b9996edd3d151614bb3582880c$7d9ddff80b91823e2a776f6329042465ad4f8a545d610ef97cdbac2c3f5265e00ff43c15300481d93a752c8bd1e183a21656b7d788e7303e67e1befb00c875bc7354dd5c3143f44065c71cb76dab65a90047edc8bc36900450ab8867af577ca5c047f5cc5640140c3f8f281da4a7206e6c2cafc24ba64f0e1a519e9231b17eb65e91cdcc0fbd28596e39922085820a65af2d8459695ad578a212028c5135de6e975f84772b662c3c4a60ae6105b2b8e525a5ac5d4d1baec3119d16dbe6aede3fe20d437e604d609173ce48a2ac1318d1ebb4fa86519f4767e077d5b605b5488b6a7287bdbe115249748268c86fb21c15
```

- `checksum` = `983ca6b9996edd3d151614bb3582880c` (16 bytes, the HMAC-MD5 edata checksum).
- `edata` = the RC4-encrypted `EncASRepPart`.
- **Truncation:** the DER declares the cipher length = **260** (`04 82 01 04`), but only **256 bytes are present** in the pcap → the **last 4 bytes of edata are missing**. Because RC4 is a stream cipher, this does **not** affect decryption of the leading bytes, so it does **not** block cracking by a plaintext/structural check. (Do not waste time "repairing" the truncation.)

---

## 4. What we tried (and why it failed)

The agent hand-rolled a pure-Python RC4-HMAC cracker (`MD4(utf-16-le pwd)` → `HMAC-MD5(k, keyusage)` → `HMAC-MD5(ksign, checksum)` → `RC4` keystream) and validated it with an **encrypt/decrypt roundtrip** (self-consistent). It cracked against:

1. **Full rockyou** (14,344,394 words, downloaded from GitHub — internet works in the sandbox) → **0 real hits**.
2. **rockyou × rule variants** (capitalisation + ~30 suffixes: digits, years 2018–2025, `!@#$`, etc.) → ran out of budget, **no confirmed hit**.
3. **Domain-themed guesses** (`forenpack`, `Forenpack`, `ForenPack`, `ad.forenpack`, `aduser1`, `htb`, seasons, …) → nothing.

### ⚠️ Three things that may be *wrong* in our approach — a planner must address these

1. **Weak validation → a false positive was mistaken for a hit.** The crack's "success" test only checked **4 structural bytes** of the decrypted plaintext (`p[8]==0x79, p[9]==0x82, p[12]==0x30, p[13]==0x82`, the `EncASRepPart` ASN.1 tags). That's only ~24–32 bits of constraint. Over 14M candidates, false positives are expected — and indeed the last run printed a "HIT" of `kgdrr` decrypting to bytes `79 82 72 3a 30 99`, where **`p[13]=0x99 ≠ 0x82`** — i.e. a **false positive**, not the password. **Fix:** validate by decrypting and confirming *much more* of the structure — ideally parse the full `EncASRepPart` (key type, nonce, `authtime`, and especially the **realm string `AD.FORENPACK.HTB` and sname `krbtgt` which appear as readable ASCII in the plaintext**). A correct password's plaintext will literally contain `FORENPACK` / `krbtgt`.
2. **Key-usage number is a single point of total failure.** The cracker used **key usage 8**. For RC4-HMAC AS-REP this is the commonly-correct Microsoft value (hashcat 18200 / impacket use it), but it was only ever verified by a *self-roundtrip* (which proves nothing about the real server). If the real AS-REP used usage **3**, **no wordlist on earth will ever match.** **Fix:** cross-validate the hash against a battle-tested tool (impacket `GetNPUsers`'s own parser, or feed the `$krb5asrep$23$` line to real **hashcat -m 18200 / john --format=krb5asrep**) so the crypto constants are not in question.
3. **No real cracking tooling was used.** No root → `apt install john/hashcat` failed; the pure-Python cracker is slow and was the only engine. The sandbox **does have internet and pip**, which opens up: downloading a **static JtR/hashcat build**, `pip install`-ing a maintained AS-REP cracker, or pulling bigger wordlists.

---

## 5. Hard constraints in the sandbox (plan around these)

- **Internet: YES** (verified — downloaded rockyou from raw.githubusercontent.com, `pip install` works). This is the big enabler.
- **No root / no sudo.** `apt-get` is blocked. Anything installed must be userspace (`pip install --user`, static binaries, source builds without system deps).
- **No `john`, `hashcat`, `tshark`, `nmap`, wordlists preinstalled.** `scapy`, `pycryptodome` (`Crypto`), `pyasn1` are available/pip-installable. `impacket` was **not** confirmed installed (pip it).
- **~8 GB RAM, ~2 CPUs** in the container.
- **Per-tool-call timeout ≈ 120 s** (controller cap). ← **this is why cracking is painful:** a long crack must be backgrounded and polled.
- **Budget:** ~$10 / attempt on Opus 4.8, ~1 hour wall-clock (whichever first — it was **cost** that killed it, at 46 min).

### 🔴 Biggest budget leak to fix (operational)
Roughly **20 of the 65 steps were the agent `sleep`-ing and polling a backgrounded cracker** (`sleep 115; cat crack.log`). **Every poll is a full, expensive Opus call that re-sends the entire growing transcript** — this burned an estimated **$3–5 of the $10 on doing nothing but waiting.** Any plan must avoid poll-loops: run the crack to completion in as few calls as possible (faster engine, or fire-and-forget to a file and check **once**, doing other analysis in between — not every ~2 minutes).

---

## 6. The target service `154.57.164.73:41314` (unsolved sub-problem)

- Accepts TCP, silent to all blind input tried. We never identified its protocol.
- Most likely it wants the **recovered `aduser1` credential** (this is "how it can be used"). Candidates for what 41314 speaks: a custom auth prompt that only responds after a valid line, Kerberos/LDAP/WinRM/SMB over a non-standard port, or a service that returns the flag once you authenticate as `aduser1`.
- **Open question for the planner:** given a cracked password, what is the most likely way to turn `aduser1:<password>` against `154.57.164.73:41314` into the flag? (And is there a smarter way to fingerprint the service than blind probing?)

---

## 7. What a good plan should deliver

Be concrete and prioritized. In particular:

1. **Make the crack *correct* before making it *bigger*:** nail down etype assignment (confirmed: etype 23 @ last position) and **key usage (3 vs 8)** using a real tool; replace the 4-byte structural check with a **plaintext-contains-`FORENPACK`/`krbtgt`** or full-ASN.1 validation to kill false positives.
2. **Then make it *strong*:** which wordlists (weakpass_3a? rockyou2021? HTB-themed? `forenpack`-seeded mutations?) and which rule sets, downloaded over the working internet, run within the time/CPU/no-root limits. Is there a faster engine we can get running userspace (static JtR, `pip` cracker, or a tight C/Cython inner loop given pure-Python is the bottleneck)?
3. **Avoid the poll-loop budget leak** — how to structure the long crack so it doesn't cost 20 Opus calls to babysit.
4. **Plan the endgame:** how to fingerprint and then use `aduser1`'s credential against `154.57.164.73:41314`.
5. **Creative alternatives** if the AS-REP simply won't crack: is there another credential/secret in the capture (the sealed LDAP, the SMB, the `github.com` thread), or a different reading of "what they stole"?

---

## 8. Raw artifacts (for reuse)

- **AS-REQ (pkt 263) hex:** `81a1a103020105a20302010aa31530133011a10402020080a20904073005a003010101a47e307ca00703050040800010a1143012a003020101a10b30091b0761647573657231a2121b1061642e666f72656e7061636b2e687462a3253023a003020102a11c301a1b066b72627467741b1061642e666f72656e7061636b2e687462a511180f32303337303931323139343830355aa7060204042587eaa8053003020117`
- **AS-REP etype-23 structure (from offset 1262):** `a003020117a103020102a282010804820104` + `983ca6b9...` (checksum) + edata (above).
- **Account:** `aduser1@AD.FORENPACK.HTB`, DONT_REQ_PREAUTH, RC4-forced.
- **Realm/DC:** `AD.FORENPACK.HTB` / `WIN-FLV7AUKV7S3` / `192.168.56.104`.
- **Target:** `154.57.164.73:41314`.
