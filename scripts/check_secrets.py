"""Pre-commit secret guard. THIS REPO IS PUBLIC — nothing credential-shaped
may enter a tracked file.

Scans staged content (or, with --all, the whole tracked tree) for credential
patterns and for the Supabase project ref, which points at a live,
internet-reachable Postgres endpoint and therefore stays in .env only.

Install as a git hook (one time):

    python scripts/check_secrets.py --install-hook

Run manually:

    python scripts/check_secrets.py           # staged changes only
    python scripts/check_secrets.py --all     # every tracked file

Exit code 1 = something looks like a secret; the commit is blocked.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / ".git" / "hooks" / "pre-commit"

# Placeholders that are *supposed* to appear in env.example and docs.
ALLOWED_PLACEHOLDERS = {
    "CHANGE_ME",
    "YOUR_PROJECT_REF",
    "your-password",
    "placeholder",
    "unset@example.com",
    "example-airline.invalid",
}

PATTERNS: list[tuple[str, str]] = [
    # Supabase project refs are 20 lowercase letters; they identify a live DB
    # host. Not a secret by design, but not for a public repo either.
    (r"\b[a-z]{20}\.supabase\.co\b", "Supabase project ref / DB host"),
    (r"\bsb_secret_[A-Za-z0-9_-]{10,}", "Supabase secret key"),
    (r"\bsb_publishable_[A-Za-z0-9_-]{10,}", "Supabase publishable key"),
    (r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}", "JWT (Supabase anon/service key?)"),
    # A populated password inside a connection URL.
    (r"://[^/\s:]+:(?!CHANGE_ME)[^/\s:@]{6,}@", "password in a connection URL"),
    (r"(?i)\b(api[_-]?key|secret|token|passwd|password)\s*[=:]\s*['\"][^'\"]{8,}['\"]", "hardcoded credential"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
]

# Files that legitimately describe the patterns above (this scanner, and the
# security notes that explain what not to commit).
SELF_EXEMPT = {"scripts/check_secrets.py"}


def _line_is_allowed(line: str) -> bool:
    return any(p in line for p in ALLOWED_PLACEHOLDERS)


def scan_text(path: str, text: str) -> list[str]:
    if path.replace("\\", "/") in SELF_EXEMPT:
        return []
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _line_is_allowed(line):
            continue
        for pattern, label in PATTERNS:
            if re.search(pattern, line):
                findings.append(f"  {path}:{lineno}: {label}")
                break
    return findings


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def staged_files() -> list[str]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    return [f for f in out.splitlines() if f.strip()]


def tracked_files() -> list[str]:
    return [f for f in _git("ls-files").splitlines() if f.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="scan all tracked files")
    parser.add_argument("--install-hook", action="store_true", help="install as pre-commit hook")
    args = parser.parse_args()

    if args.install_hook:
        HOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        HOOK_PATH.write_text(
            "#!/bin/sh\n"
            'exec python "$(git rev-parse --show-toplevel)/scripts/check_secrets.py"\n'
        )
        HOOK_PATH.chmod(0o755)
        print(f"Installed pre-commit hook at {HOOK_PATH}")
        return 0

    files = tracked_files() if args.all else staged_files()
    findings: list[str] = []
    for f in files:
        content = _git("show", f":{f}") if not args.all else None
        if not content:
            fp = REPO_ROOT / f
            if not fp.is_file():
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        findings.extend(scan_text(f, content))

    if findings:
        print("BLOCKED — possible secrets detected (this repo is PUBLIC):")
        print("\n".join(findings))
        print("\nMove the value into .env (gitignored). If it is genuinely a")
        print("placeholder, add it to ALLOWED_PLACEHOLDERS in scripts/check_secrets.py.")
        return 1

    print(f"check_secrets: clean ({len(files)} file(s) scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
