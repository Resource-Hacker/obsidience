#!/usr/bin/env python3
"""Fail if the graph demo's published files carry anything not public.

Checks every file under the given directories (default: the generated data and
the built demo) for:

- text from this installation's live Vault (``obsidience/vault``, never
  published): any 6-word run or Article title that appears in the output but
  not in the public corpus (the starter Vault, DESIGN.md, README.md, docs/ and
  commit subjects);
- e-mail addresses, IPv4 addresses other than loopback, MAC and PCI addresses,
  GPU UUIDs, home and runtime paths, API keys and bearer tokens;
- private names, accounts, device serials and this machine's user and host
  name, from a local list that is never committed (``OBSIDIENCE_LEAK_TERMS``,
  default ``~/.config/obsidience/leak-check-terms.sha256``: one term or its
  lower-case SHA-256 per line). Without that list (CI, other machines) this
  pass is skipped and the summary says so.

Usage: .venv/bin/python obsidience/ui/demo/leak_check.py [DIR ...]
Exits 1 and prints each finding when anything matches.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
REPO = DEMO.parents[2]
DEFAULT_DIRS = [DEMO / "public" / "data", REPO / "obsidience" / "ui" / "out" / "demo"]
WORD = re.compile(r"[a-z0-9][a-z0-9'_-]*")
N = 6
TEXT = {".md", ".py", ".ts", ".tsx", ".js", ".mjs", ".qml", ".json", ".toml", ".yml", ".yaml", ".txt", ".sh", ".css", ".html"}

PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "ipv4": re.compile(r"\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"),
    "mac": re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.IGNORECASE),
    "pci": re.compile(r"\b(?:0000:)?[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\b"),
    "gpu-uuid": re.compile(r"\bGPU-[0-9a-f]{8}-", re.IGNORECASE),
    "home-path": re.compile(r"/home/[A-Za-z]|/run/user/\d|/tmp/claude|~/\.config|\\Users\\"),
    "secret": re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b"
                         r"|\bBearer\s+[A-Za-z0-9._~+/-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY", re.IGNORECASE),
    "timezone": re.compile(r"America/\w+|Europe/\w+|T\d\d:\d\d:\d\d(?:\.\d+)?[+-](?!00:00)\d\d:\d\d|\bP[DS]T\b"),
}


def sha(text: str) -> str:
    return hashlib.sha256(text.lower().encode()).hexdigest()


def private_terms_path() -> Path:
    default = Path.home() / ".config" / "obsidience" / "leak-check-terms.sha256"
    return Path(os.environ.get("OBSIDIENCE_LEAK_TERMS", default)).expanduser()


def private_hashes() -> set[str]:
    """Hashes of the local private-term list, plus this machine's identity; empty without the list."""
    path = private_terms_path()
    if not path.is_file():
        return set()
    hashes = set()
    for line in path.read_text().splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            hashes.add(value if re.fullmatch(r"[0-9a-f]{64}", value) else sha(value))
    for value in (getpass.getuser(), socket.gethostname().split(".")[0]):
        hashes.add(sha(value))
    return hashes


def scan(text: str, hashes: set[str]) -> list[str]:
    """Pattern and private-term findings in one text."""
    findings = []
    for kind, pattern in PATTERNS.items():
        for match in sorted(set(pattern.findall(text)))[:5]:
            findings.append(f"{kind}: {match[:80]!r}")
    tokens = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", text))
    tokens |= {part for token in tokens for part in re.split(r"[._-]", token) if len(part) > 2}
    findings += [f"private term (sha256 {sha(token)[:12]})" for token in sorted(tokens) if sha(token) in hashes]
    return findings


def ngrams(text: str, skip: frozenset[str] = frozenset()) -> set[int]:
    """Hashes of every N-word run, except runs made only of `skip` words."""
    words = WORD.findall(text.lower())
    return {hash(" ".join(words[i:i + N])) for i in range(len(words) - N + 1)
            if not skip or not all(word in skip for word in words[i:i + N])}


def identifier_words() -> frozenset[str]:
    """Words of the public Tool and Skill names: lists of them are not prose."""
    vault = REPO / "obsidience" / "defaults" / "vault"
    names = [path.stem for folder in ("Tools", "Skills") for path in (vault / folder).rglob("*.md")]
    return frozenset({"skills", "tools", "skill", "tool"} | {part.lower() for name in names
                                                              for part in re.split(r"[._-]", name) if part})


def strings(value, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            out.append(str(key))
            strings(child, out)
    elif isinstance(value, list):
        for child in value:
            strings(child, out)


def output_text(dirs: list[Path]) -> dict[str, str]:
    texts = {}
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in {".json", ".js", ".html", ".css", ".txt", ".md", ".svg"}:
                continue
            raw = path.read_text(errors="replace")
            if path.suffix == ".json":
                parts: list[str] = []
                strings(json.loads(raw), parts)
                raw = "\n".join(parts)
            texts[str(path.relative_to(REPO) if path.is_relative_to(REPO) else path)] = raw
    return texts


def public_corpus() -> str:
    """Every tracked text file of the repository plus its commit messages: already public."""
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout
    parts = []
    for name in tracked.splitlines():
        path = REPO / name
        if path.suffix in TEXT and path.is_file() and path.stat().st_size < 2_000_000:
            parts.append(path.read_text(errors="replace"))
    parts.append(subprocess.run(["git", "-C", str(REPO), "log", "--format=%s%n%b"], capture_output=True,
                                text=True, check=True).stdout)
    return "\n".join(parts)


def live_vault() -> Path | None:
    common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    vault = Path(common).parent / "obsidience" / "vault"
    return vault if vault.is_dir() else None


def main() -> int:
    dirs = [Path(arg).resolve() for arg in sys.argv[1:]] or DEFAULT_DIRS
    texts = output_text(dirs)
    if not texts:
        print("No output files found in", ", ".join(map(str, dirs)))
        return 1
    findings = []
    hashes = private_hashes()
    for name, text in texts.items():
        # The built bundle is compiled from the tracked UI source, which is
        # already public: check it for patterns, not for names in that source.
        bundle = "/assets/" in name and name.endswith((".js", ".css"))
        findings += [f"{name}: {finding}" for finding in scan(text, set() if bundle else hashes)]
    output = "\n".join(texts.values())
    out_grams = ngrams(output)
    vault = live_vault()
    checked = 0
    if vault is not None:
        public = public_corpus()
        public_grams = ngrams(public)
        public_lower = public.lower()
        skip = identifier_words()
        for path in vault.rglob("*.md"):
            if any(part.startswith(".") for part in path.parts):
                continue
            body = path.read_text(errors="replace")
            checked += 1
            # Prose only: front-matter lists and [[links]] repeat public Tool and Skill names.
            prose = re.sub(r"\[\[[^\]]*\]\]", " ", re.sub(r"\A---\n.*?\n---\n", "", body, flags=re.DOTALL))
            hits = (ngrams(prose, skip) & out_grams) - public_grams
            if hits:
                words = WORD.findall(prose.lower())
                example = next(" ".join(words[i:i + N]) for i in range(len(words) - N + 1)
                               if hash(" ".join(words[i:i + N])) in hits)
                findings.append(f"live Vault text in output: {path.relative_to(vault)} ({len(hits)} six-word runs, "
                                f"e.g. {example!r})")
            title = re.search(r"^title:\s*['\"]?(.+?)['\"]?\s*$", body, re.MULTILINE)
            if title:
                value = title.group(1).strip()
                if len(value) >= 8 and " " in value and value.lower() not in public_lower and value in output:
                    findings.append(f"live Vault title in output: {value!r}")
    for finding in findings:
        print("LEAK", finding)
    terms = (f"{len(hashes)} private-term hashes" if hashes
             else f"no private-term pass (no local list at {private_terms_path()})")
    vault_note = f"{checked} live Vault Articles" if vault is not None else "no live Vault (pass skipped)"
    print(f"checked {len(texts)} files ({sum(map(len, texts.values())):,} characters) against "
          f"{len(PATTERNS)} patterns, {terms} and {vault_note}: {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
