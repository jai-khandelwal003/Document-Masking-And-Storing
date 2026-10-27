#!/usr/bin/env python3
"""Block commits that contain secrets or private data files.

  python tools/scan_secrets.py --staged   # what the pre-commit hook runs (added lines + file names)
  python tools/scan_secrets.py --all      # every tracked file (used in CI)

Add `secret-scan: ignore` to a line to allow a deliberate false positive.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

BLOCKED_PATHS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.sqlite",
    "*.sqlite3",
    "*.bak.zip",
    "output/*",
    ".images/*",
    "backup/*",
    ".venv/*",
    "deployment/certs/*",
]
ALLOWED_PATHS = [".env.example"]

SPECIFIC_PATTERNS = [
    ("Clerk/Stripe secret key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
]

# NAME = value, where the name looks sensitive and the value looks like a literal (no code characters).
GENERIC = re.compile(
    r"""(?ix)
    \b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API_?KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)
    \s*[:=]\s*["']?([^\s"'#,;(){}\[\]]{16,})
    """
)
PLACEHOLDER = re.compile(
    r"(?i)(change-?me|your[-_ ]|example|dummy|placeholder|xxxx|\*{3,}|<[^>]+>|\$\{|%\(|os\.environ|environ\.get|\.get\(|demo|\.\.\.)"
)
GENERIC_SKIPPED_PREFIXES = ("tests/",)
BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".traineddata", ".ico", ".woff", ".woff2")
IGNORE_MARKER = "secret-scan: ignore"


def looks_random(value):
    """Heuristic: long literal that mixes letters and digits (or symbols), or a long hex string."""
    if len(value) < 16 or value[0] in "_$" or "." in value:
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32,}", value):
        return True
    has_digit = any(c.isdigit() for c in value)
    has_letter = any(c.isalpha() for c in value)
    if not (has_digit and has_letter):
        return False
    mixed_case = any(c.isupper() for c in value) and any(c.islower() for c in value)
    return mixed_case or any(c in "!@#$%^&*+/=~" for c in value)


def blocked_path(path):
    normalized = path.replace("\\", "/")
    base = os.path.basename(normalized)
    if normalized in ALLOWED_PATHS or base in ALLOWED_PATHS:
        return False
    return any(fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(base, pat) for pat in BLOCKED_PATHS)


def _redact(value):
    return value[:4] + "****" if len(value) > 4 else "****"


def scan_line(path, line):
    """Return a list of (kind, redacted_match) for one line."""
    if IGNORE_MARKER in line:
        return []
    found = []
    for kind, pattern in SPECIFIC_PATTERNS:
        match = pattern.search(line)
        if match:
            found.append((kind, _redact(match.group(0))))
    normalized = path.replace("\\", "/")
    if not normalized.startswith(GENERIC_SKIPPED_PREFIXES):
        for match in GENERIC.finditer(line):
            value = match.group(2)
            if looks_random(value) and not PLACEHOLDER.search(value) and not PLACEHOLDER.search(match.group(0)):
                found.append((f"Hard-coded value for {match.group(1)}", _redact(value)))
    return found


def scan_text(path, text):
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for kind, snippet in scan_line(path, line):
            findings.append((path, number, kind, snippet))
    return findings


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def scan_staged():
    findings = []
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
    for name in names:
        if blocked_path(name):
            findings.append((name, 0, "File must not be committed", name))
    diff = _git("diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR")
    current, line_no = "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            line_no = int(match.group(1)) - 1 if match else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            line_no += 1
            if current and not current.lower().endswith(BINARY_SUFFIXES):
                for kind, snippet in scan_line(current, raw[1:]):
                    findings.append((current, line_no, kind, snippet))
    return findings


def scan_all():
    findings = []
    for name in _git("ls-files").splitlines():
        if blocked_path(name):
            findings.append((name, 0, "File must not be committed", name))
            continue
        if name.lower().endswith(BINARY_SUFFIXES) or not os.path.isfile(name) or os.path.getsize(name) > 1_000_000:
            continue
        with open(name, "rb") as handle:
            data = handle.read()
        if b"\x00" in data:
            continue
        findings.extend(scan_text(name, data.decode("utf-8", errors="replace")))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan staged changes (default)")
    mode.add_argument("--all", action="store_true", help="scan every tracked file")
    args = parser.parse_args()

    findings = scan_all() if args.all else scan_staged()
    if not findings:
        print("secret scan: clean")
        return 0

    print("secret scan: possible secrets or private files found:\n", file=sys.stderr)
    for path, line, kind, snippet in findings:
        location = f"{path}:{line}" if line else path
        print(f"  {location}  {kind}  [{snippet}]", file=sys.stderr)
    print(
        "\nRemove the secret (and rotate it if it was ever pushed), unstage the file, or add "
        f"'{IGNORE_MARKER}' to a deliberate false positive.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
