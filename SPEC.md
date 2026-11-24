# Valt — Container Format Spec (v1)

> One `.valt` file. Many folders. Each folder behind its own password.
> Open it with one password and you see **only** what that password unlocks —
> everything else is indistinguishable from random noise.

This is the single source of truth for the format. It is written to be
**implemented by one person, line by line**, with no crypto background — every
rule below comes with its reason. If code and this document ever disagree,
this document wins.

---

## 1. The promise (what v1 must achieve)

The whole point of the project, stated as testable properties:

- **P1 — No way in without a password.** Every byte except the first 8 is either
  ciphertext or random junk. There is no second way to read the data: no
  "open with 7-zip", no "rename to .zip", no strings in a hex editor.
- **P2 — No proof of hidden data.** The file cannot reveal how many folders it
  holds, their names, sizes, or file counts. An empty container and a
  half-full one look identical from the outside.
- **P3 — One password sees one world.** Password A's open shows A's folders and
  *nothing about* B's — not even that B exists.
- **P4 — Wrong password = empty container.** The app always answers
  *"No compartments found for this password"* — for a wrong password and for a
  genuinely empty file alike. It cannot tell the difference, so it must not
  pretend to.
- **P5 — Tampering never yields data.** Flip, cut, or splice any byte anywhere →
  clean refusal. The app never decrypts "mostly right" data.
- **P6 — Password guessing is expensive.** Each guess costs a full ~1-second
  memory-hard computation *per safe*. 
- **P7 — Unlocked data lives only in RAM.** The disk only ever sees ciphertext
  (plus files you explicitly extract). No temp files, no logs, no cache.

Section 9 turns each promise into a hands-on test you can run yourself.

---

## 2. Words you need

| Term | Meaning |
|---|---|
| **container** | the `.valt` file |
| **compartment** | one folder locked behind one password |
| **safe** | a 128-byte record that binds one password to one compartment |
| **folder key** | 32 fresh random bytes; scrambles one compartment |
| **password key** | the password boiled with Argon2; locks a safe |
| **segment** | the slice of the file where one compartment's data lives |
| **index** | a tiny encrypted JSON: the compartment's file list |

---

## 3. What we use (and nothing else)

| Piece | From | Job |
|---|---|---|
| ChaCha20-Poly1305 (AEAD) | `cryptography` | scramble **and** seal — any tamper is detected |
| Argon2id | `argon2-cffi` (`low_level.hash_secret_raw`) | password → 32-byte key, slow and memory-hungry on purpose |
| `secrets` | stdlib | all randomness (keys, salts, nonces, junk) |
| `struct` | stdlib | pack ints into bytes (`<H` u16, `<I` u32, `<Q` u64, little-endian) |
| `json` | stdlib | build/parse the encrypted index |
| `os.walk` | stdlib | walk the folder when packing |

All integers in the file are **little-endian**.

---

## 4. The file, byte by byte

```
┌─────────────────────────────────────────────────┐
│ header (8 bytes)                                │  plain
│ safe #0 (128 bytes)                             │
│ safe #1 (128 bytes)                             │
│ … one safe per slot …                           │  each: salt + nonce + locked payload
├─────────────────────────────────────────────────┤
│ segment #0: [ index blob | file chunks … ]      │
│ segment #1: [ index blob | file chunks … ]       │
│ …                                               │
│ segment #N: [ index blob | file chunks … ]      │
│ (tiny junk tail, if any)                        │
└─────────────────────────────────────────────────┘
```

**Safe k guards segment k.** That positional rule is what lets us skip an
allocation table entirely (an allocation table in plaintext would leak how much
of the file is really used — breaking P2).

### 4.1 Header — 8 bytes at offset 0

| offset | size | field | rule |
|---|---|---|---|
| 0 | 4 | magic | `b"VALT"` — identification only, never "validation" |
| 4 | 2 | version | u16 = `1` |
| 6 | 2 | slot_count | u16, allowed `2..16`, default `8` |

### 4.2 Safe k — 128 bytes at `8 + 128·k`

| offset | size | field | rule |
|---|---|---|---|
| 0 | 16 | salt | fresh random, **unique per safe** |
| 16 | 12 | nonce | fresh random |
| 28 | 100 | ciphertext+tag | `AEAD(password_key, nonce, payload, aad)` |

- `aad` = the 8 header bytes + `<H` slot index → each safe is welded to its
  container and position (Law 5 explains why).
- **An empty safe = 128 random bytes.** Indistinguishable from a locked one —
  that's P2.

Payload inside a safe (≤ 84 bytes plaintext):

| size | field | rule |
|---|---|---|
| 32 | folder_key | fresh random per compartment write (Law 1) |
| 8 | index_len | u64, total size of the index blob |
| 1 | name_len | u8, `0..43` |
| ≤ 43 | name | UTF-8 label shown after unlock (optional; keep it innocuous) |

### 4.3 Segments

```
data_offset  = 8 + 128 · slot_count
segment_len  = (file_size − data_offset) // slot_count
segment k    = [data_offset + k · segment_len, + segment_len)
```

- The **creator** rounds the chosen file size up to a multiple of
  `slot_count × 64 KiB`, so the division is exact and each segment is equal.
- The reader uses floor division; a few junk tail bytes are tolerated.
- Minimum segment size: 1 MiB.

### 4.4 Inside a segment

```
[ index blob (index_len bytes) ][ file data area ]
```

- **Index blob** at segment start: `nonce(12) + AEAD(folder_key, nonce, json)`.
  The plaintext is the index JSON below.
- **File data area** begins at `index_len` within the segment. Every per-file
  `start` in the index is a byte offset **relative to the data area**.

### 4.5 Index (encrypted JSON, UTF-8)

```json
[
  {"name": "photos/cat.jpg", "start": 0, "size": 3112445},
  {"name": "docs/notes.txt", "start": 3145728, "size": 12004}
]
```

- `name`: path relative to the packed folder, forward slashes, no leading `/`,
  no `..`, UTF-8, ≤ 1024 bytes.
- A file's **file number** is its position in this list (0, 1, 2, …).
- The reader **must** reject any `name` that escapes the extraction root,
  any `start`/`size` reaching outside the segment, and any malformed JSON.
  Fail closed (Law 6).

### 4.6 File chunks

Each file is cut into **64 KiB chunks** (65536 bytes; last chunk may be short)
and each chunk is sealed on its own:

```
chunk c of file f (bytes [c·65536, min((c+1)·65536, size)) of the file):
  nonce = <I f> + <Q c>        # 4+8 = 12 bytes: WHICH file, WHICH chunk
  data  = AEAD(folder_key, nonce, chunk_plaintext, aad=None)
```

The `(file, chunk)` pair is the whole nonce story: all files share one folder
key, so the nonce must name the file *and* the chunk — that makes every chunk
in the compartment unique, and a repeat mathematically impossible (Law 2).

---

## 5. The laws (crypto rules — never break these)

1. **Fresh key on every (re)write.** Writing or rebuilding a compartment
   always generates a *new* random folder key and rewraps its safe. This kills
   every cross-version nonce-reuse problem in one move: an old copy of the
   container shares no (key, nonce) with the new one.
2. **Never reuse (key, nonce).** The one catastrophic mistake. Law 1 plus the
   `(file, chunk)` nonce makes it impossible by construction.
3. **All randomness from `secrets`.** Never the `random` module (it's
   predictable). Keys, salts, nonces, junk — all of it.
4. **AEAD only.** No unauthenticated mode anywhere, ever. If a decryption lacks
   a tag, it's not encryption, it's decoration.
5. **The header and salt live with the data they protect.** KDF parameters are
   *fixed by this spec* (no parameter fields in the file → nothing for an
   attacker to weaken). The safe's `aad` binds each safe to this container and
   slot, so a safe spliced into another file fails its tag.
6. **Fail closed, and quietly.** Any invalid magic/version/length/JSON/path →
   one error message: *"invalid or corrupted container."* No byte offsets, no
   partial decryption, no details.
7. **Every unused byte is CSPRNG junk.** Written at creation. Free segments,
   free space inside a segment, the tail — all random. Occupancy is invisible.
8. **Plaintext lives in RAM only.** Stream one chunk at a time; the index is
   tiny so it may sit in RAM; never write unlocked bytes to disk unless the
   user asked for extraction. No logging of names, paths, or passwords.

**Argon2id parameters (fixed for v1):** salt = the safe's 16 bytes,
`memory_cost=65536` (64 MiB), `time_cost=3`, `parallelism=1`, output 32 bytes.
No per-user tuning in v1 — that would need parameter fields in the file, and
v1 deliberately has none. Tuning arrives with a v2 format bump.

**Open-time cost, stated honestly:** trying a password runs Argon2id once per
safe → with 8 safes that's ~8 seconds, sequential. That slowness is the security
(P6), just showing up as patience. (Parallel trials are a v2 optimization.)

---

## 6. Operations

### create
1. Ask for: file path, total size, `slot_count` (default 8).
2. Validate size: `file_size ≥ data_offset + slot_count × 1 MiB`; round up to a
   multiple of `slot_count × 64 KiB`.
3. Write the header, then fill the *entire rest of the file* with random junk.
4. For each compartment the user adds (slot 0, 1, 2, …): pick folder,
   password, optional name →
   - fresh folder key → walk the folder, chunk-locking every file into
     segment k while building the index JSON →
   - lock the index blob at the segment start →
   - derive the password key with fresh salt, wrap the safe.
5. Slots the user never filled keep their junk (they're "empty safes").

### open
1. Read and validate the header (magic, version, slot_count range, size).
2. Ask for a password (prompt — never the command line).
3. For each safe: `password_key = Argon2id(pw, salt_k)` → try to unlock →
   success gives the folder key → decrypt that segment's index.
4. Show every compartment that opened. **Zero opened →
   "No compartments found for this password."** (P4)
5. The same password in several safes → they all open together (that's how
   password groups work, with no extra code).

### extract
From an open compartment, for each chosen file: seek to
`segment_start + index_len + start`, decrypt chunk by chunk (nonce
`(file, chunk)`), write to the destination after sanitizing the path.
RAM used: one chunk.

### add to an existing container (use with care)
The app cannot know which safes are secretly occupied (that's P2 working
against us, too). So the app must:
1. Show which slots your entered passwords opened.
2. Ask you to pick one of the *remaining* slot numbers, with this warning
  verbatim: *"If this slot secretly holds a compartment whose password you
  have forgotten, writing here will destroy it."*
3. Write the new compartment into that slot's segment, per Law 1.

Creating everything up front is the safe path; adding later is the flexible
one. Both are allowed; the warning is mandatory.

### change password
Unwrap with the old password (you get the folder key and payload), then rewrap
the same payload with a fresh salt + nonce and the new password key. Instant —
no data re-encryption.

### remove
Overwrite that safe with fresh random bytes. Optionally shred the segment too
(refill with random). Note loudly: **old backups of the container still contain
the data.**

### verify
Re-decrypt every chunk of an unlocked compartment and report the first file
that fails to authenticate (naming unlocked files is fine — they're unlocked).

---

## 7. Password rules

- Prompt via `getpass` / a password field. **Never** as a command-line
  argument (shell history and process lists would keep it forever).
- Refuse passwords under 8 characters. Recommend diceware-style passphrases
  (5+ words ≈ 64+ bits) or a long, memorable passphrase.
- **There is no recovery.** A forgotten password means the compartment is
  gone. The app says so, in plain words, at creation time. No hints, no
  backdoors, no exceptions — a backdoor for you is a backdoor for everyone.

---

## 8. The app must never

- Say "wrong password" (P4 — it cannot know that).
- Show or hint at the number of locked compartments (it cannot know that either).
- Write plaintext to disk outside explicit extraction (P7).
- Log names, paths, or passwords.
- Decrypt on any failure path — a failed tag ends the operation, full stop.

---

## 9. Acceptance tests (prove the promise, on a copy)

| # | Test | Expected |
|---|---|---|
| 1 | `strings container.valt` | nothing but `VALT` |
| 2 | rename to `.zip`, open in 7-zip / file manager | fails — it isn't a zip or any known format |
| 3 | open with a never-used password vs. open an empty container | identical message, no hint |
| 4 | open with password A while B exists | A's folders only; zero mention of B |
| 5 | flip/cut any byte in a copy | clean "invalid or corrupted" refusal, no partial data |
| 6 | create two containers from the same folder + same password | the two files differ completely (random keys, salts, junk) |
| 7 | full round-trip: pack → open → extract | byte-identical (compare SHA-256 hashes) |
| 8 | hexdump of the data region | no recognizable content; file sizes not visible anywhere |
| 9 | keep a copy, remove a compartment, open the copy | the old copy still opens it (removal ≠ gone from backups) |

Every release candidate passes all nine. Test 5 is also an automated unit
test: flip each byte of a small container, expect refusal, never wrong data.

---

## 10. Honest limits (ship these in the README)

- Two snapshots of the file over time show *that* it changed (not what's
  inside). Create once, never modify, for maximum deniability.
- Backups keep everything you ever removed.
- Windows can copy RAM to disk (pagefile/hibernation). Every local encryption
  tool shares this exposure; close the app when done, disable hibernation if
  extra careful.
- Malware running while you use the app sees everything. Out of scope.
- A compartment cannot outgrow its segment size (make the container bigger).
- Add-later can destroy a forgotten compartment (hence §6's warning).
- Forgot the password → gone (§7).

---

## 11. Build order — twelve small stages

The rule of this build order: **never build on top of something you haven't
watched work.** Every stage ends with something you can run, see, or test —
there is no "it will all come together at the end."

Files appear in this order (flat `valt/` folder, run everything from the repo
root — no packaging gymnastics; a `pyproject.toml` only shows up at Stage 12):

```
Valt/
├── SPEC.md
├── valt/
│   ├── __init__.py     ← Stage 0   (one empty file)
│   ├── crypto.py       ← Stage 1   the six small tools
│   ├── safes.py        ← Stage 3   the 128-byte safe, in memory
│   ├── container.py    ← Stages 4–7, 9   the file itself
│   └── cli.py          ← Stage 8   the commands you type
└── tests/
    ├── test_crypto.py      ← Stage 2
    ├── test_safes.py       ← Stage 3
    ├── test_container.py   ← Stage 4
    └── test_roundtrip.py   ← Stages 6–7
```

### Stage 0 — Setup *(half an hour)*
Activate `.venv`, `pip install cryptography argon2-cffi pytest`, create
`valt/` and `tests/`, add an empty `valt/__init__.py`.
**Done when:** `python -c "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305; from argon2.low_level import hash_secret_raw; print('ok')"` prints `ok`.

### Stage 1 — `crypto.py`, the toolbox *(~60 lines + a REPL day)*
Write `new_key()`, `random_bytes(n)`, `password_to_key(pw, salt)` (the spec
params), `lock(key, nonce, data, aad=None)`, `unlock(...)`, and the
`<H`/`<I`/`<Q` int-packing helpers.
Then **play in the REPL, no project code yet:** lock a string and unlock it;
unlock with a different key → watch it throw; flip one byte of the ciphertext
→ watch it throw; time `password_to_key` (~1 second — feel the security).
**Done when:** all four experiments behaved exactly as expected.
*You learn:* AEAD, real randomness, key derivation — and that errors **are**
the security signal.

### Stage 2 — `test_crypto.py`: the habit *(~50 lines)*
With pytest: round-trip works; wrong key raises; tamper raises; same password
with two different salts → two different keys; int pack/unpack round-trip.
**Done when:** `pytest` is green — and stays green forever after.
*You learn:* testing "must fail" behavior, not just "must work".

### Stage 3 — `safes.py`: the trick, in pure memory *(~70 lines)*
Write `build_payload(folder_key, index_len, name)`, `parse_payload(...)`,
`wrap_safe(password, payload, aad)` → 128 bytes, and
`try_open_safe(password, safe, aad)` → payload or `None`.
No files involved — a safe is just 128 bytes in RAM.
Tests: right password opens; wrong password → `None`; 128 random bytes (an
"empty safe") → `None`; a tampered safe → `None`.
**Done when:** locked, empty, and broken safes are all just `None` to the
code — indistinguishable. That *is* the privacy property, already working.
*You learn:* the heart of the whole format, five small functions at a time.

### Stage 4 — the empty container *(~80 lines in `container.py`)*
Write `create_empty(path, size, slot_count)` — header, then junk written in
1 MiB pieces (never one giant buffer) — plus `read_header(path)` (validates
magic, version, slot_count, minimum size) and `segment_geometry(...)`.
Tests: read back what you wrote; corrupt the magic / version / slot_count in
a copy → clean `FormatError`.
**Done when:** acceptance tests 1 and 2 pass on a real file on disk
(`strings` shows only `VALT`; renaming to `.zip` gets you nowhere).
*You learn:* binary files — offsets, `seek`, streaming writes, fail-closed parsing.

### Stage 5 — pack one folder (the write side) *(~120 lines)*
Write `pack_folder(path, slot, folder, folder_key) -> index_len`:
walk the folder with `os.walk`, normalize names, compute each file's `start`,
build the index JSON, lock it, write it at the segment start, then stream each
file in 64 KiB chunks — nonce = `<I file#> + <Q chunk#>`.
Check the folder fits the segment **before writing anything**.
**Done when:** hexdump of the segment is pure noise (test 8), and you can
hand-decrypt one chunk in the REPL using the folder key.
*You learn:* `os.walk`, path sanitizing, streaming, and the nonce law in practice.

### Stage 6 — the read side: list + extract *(~100 lines) — first big milestone*
Write `read_index(...)`, `extract_file(...)` (reject `..`, stream chunks out,
check sizes), `extract_all(...)`.
Test with a deliberately awkward tree: subfolders, an **empty file (zero
chunks!)**, a file of exactly 64 KiB, a unicode filename.
**Done when:** pack → extract → every file's SHA-256 is identical (test 7).
*You learn:* reading by offset, path-traversal defense, and the feeling of a
green round-trip test.

### Stage 7 — wire it together: `create` + `open` *(~80 lines) — the Valt moment*
Write `create(path, size, [(folder, password, name), ...])` and
`open(path, password)` — try every safe, collect every hit, read each index,
and print *"No compartments found for this password."* on zero hits.
Tests: three compartments — each password sees only its own (test 4); a
never-used password behaves exactly like an empty container (test 3); two
containers built from the same input differ completely (test 6); the same
password in two slots opens both.
**Done when:** you open with password A and see only A, open with password B
and see only B — same file. The project is now real.
*You learn:* how the pieces become a product.

### Stage 8 — `cli.py`: something you can actually use *(~150 lines)*
`argparse` subcommands `create` / `open` / `extract`; `getpass` prompts
(never argv passwords); refuse passwords under 8 characters; per-file progress.
**Done when:** a friend can create and open a container following only the
app's own output; acceptance tests 1–8 pass by hand.
*You learn:* the rules of §7 and §8 get enforced by the interface itself.

### Stage 9 — the remaining verbs *(~100 lines)*
`change_pw` (unwrap → rewrap, instant), `remove` (wipe the safe, optional
segment shred), `verify` (full re-decrypt of what's unlocked), `add-later`
(with §6's mandatory warning).
Plus the automated tamper sweep: flip **every** byte of a small container, one
test at a time — every flip must be a clean refusal (test 5, automated).
**Done when:** test 9 also passes — an old copy still opens a removed
compartment, proving removal ≠ gone from backups, on purpose and documented.

### Stage 10 — README + dogfooding *(no new code)*
Write the README: what it is, how to use it, the §10 honest limits, and one
loud line: **learning project — get it reviewed before trusting it with real
secrets.** Then store a real folder of yours in it for a week and write down
every annoying moment. That list is the v2 plan.

### Stage 11 — GUI *(optional, later)*
A PySide6 window: create wizard, unlock view, progress bars. Rules: password
fields, no plaintext in temp files, show only unlocked compartments. Only
start this once the CLI is boring and solid.

### Stage 12 — the exe *(optional, last)*
PyInstaller *onedir* plus an Inno Setup installer, tested on a machine with
no Python installed. Expect antivirus grumpiness toward an unsigned crypto
exe — submit false positives, document the SmartScreen warning.

---

## 12. Deliberately left for v2

Parallel safe trials · per-machine Argon2 tuning (needs a v2 format) ·
unequal segments · streaming index for tens of thousands of files · GUI ·
PyInstaller exe · a segment-shredding tool. None of these are needed for v1 to
keep every promise in section 1.
