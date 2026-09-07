"""Evaluate candidate source URLs against their host's live robots.txt.

    python scripts/check_robots.py
    python scripts/check_robots.py --url https://example.com/some/file.pdf

Phase 0 verified IndiGo's tariff URL by fetching robots.txt and searching it
for the URL's *path*. That found nothing and produced a verdict of ALLOWED.
The real file contained `Disallow: *.pdf` — a rule matching by file extension,
invisible to a path search — and the collector spent Phase 1 fetching a
disallowed URL. See docs/06-recon-log.md, "Correction".

The lesson is that a robots.txt check is not a text search; it is a parser
evaluating a specific URL for a specific agent. This script is that check, made
repeatable, so the mistake is not available to make again by hand.

It deliberately reuses the *production* RobotsGate from apix.acquisition.
compliance rather than reimplementing the logic, so the verdict printed here is
by construction the same verdict the collector will reach at runtime.

Read-only reconnaissance: it fetches robots.txt and nothing else. It never
requests the candidate URL itself.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apix.acquisition.compliance import APIX_AGENT_TOKEN, RobotsGate

# Candidate Tier-1 tariff-sheet URLs from docs/06-recon-log.md. IndiGo and Air
# India Express are known-blocked and kept as controls: a run that does not
# report them as blocked means this script itself has regressed.
CANDIDATES: list[tuple[str, str]] = [
    ("IndiGo (control: known BLOCKED)",
     ("https://www.goindigo.in/content/dam/s6web/in/en/assets/documents/"
      "IndiGo-Tariff-Sheet-2026-05-08.pdf")),
    ("Air India Express (control: known BLOCKED)",
     ("https://www.airindiaexpress.com/content/dam/airindiaexpress/documents/"
      "Air_India_Express_Tariff_Sheet.pdf")),
    ("Air India",
     ("https://www.airindia.com/content/dam/air-india/pdfs/tariff/"
      "TARIFF-SHEET-AS-ON-15JUN26.pdf")),
    ("Akasa Air",
     "https://assets.akasaair.com/f/159922/x/c1ce86c83e/fare-sheet-akasa-air.pdf"),
    ("SpiceJet (tariff URL not yet located — probing a plausible path)",
     "https://corporate.spicejet.com/mandatory-disclosure.aspx"),
]


def _rule_to_regex(pattern: str) -> re.Pattern[str]:
    """robots.txt path matching: `*` is any sequence, `$` anchors the end,
    and a pattern is matched as a prefix of the path unless anchored."""
    out = []
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        elif ch == "$":
            out.append("$")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out))


def explain(robots_body: str, url: str) -> list[str]:
    """Which Disallow rules actually match this URL's path.

    protego gives the verdict but not the reason. When a URL is refused, the
    reason is the whole point -- 'blocked' is not actionable, 'blocked by
    a site-wide *.pdf rule' is.
    """
    path = urlparse(url).path or "/"
    matches: list[str] = []
    in_star_group = False
    for raw in robots_body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            in_star_group = value == "*" or value.lower() == APIX_AGENT_TOKEN.lower()
        elif field == "disallow" and in_star_group and value and _rule_to_regex(value).match(path):
            matches.append(value)
    return matches


def check(label: str, url: str) -> bool:
    gate = RobotsGate()
    verdict = gate.check(url)
    host = urlparse(url).netloc

    status = "ALLOWED" if verdict.allowed else "BLOCKED"
    print(f"\n{label}")
    print(f"  url     : {url}")
    print(f"  robots  : {verdict.robots_url}")
    print(f"  verdict : {status}  (agent: {APIX_AGENT_TOKEN})")
    if verdict.crawl_delay:
        print(f"  crawl-delay: {verdict.crawl_delay}s")

    # Reach into the gate's parsed cache to explain the verdict.
    body = None
    try:
        body = gate._fetch_robots(verdict.robots_url)
    except Exception as exc:  # noqa: BLE001 - reporting, never fatal
        print(f"  note    : could not re-read robots.txt to explain ({exc})")

    if body:
        rules = explain(body, url)
        if rules:
            print(f"  matched : {', '.join(repr(r) for r in rules)}")
        elif not verdict.allowed:
            print("  matched : (protego says blocked but no rule was identified — inspect by hand)")
    elif "unreachable" in verdict.reason:
        print(f"  note    : {verdict.reason}")
        print(f"  caution : no published rules retrievable for {host}. RFC 9309 treats that "
              f"as unrestricted, but it is an UNVERIFIED allow, not a confirmed one.")
    return verdict.allowed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", help="check this URL instead of the candidates")
    args = parser.parse_args()

    targets = [("ad hoc", u) for u in args.url] if args.url else CANDIDATES

    print(f"robots.txt evaluation for agent token: {APIX_AGENT_TOKEN}")
    print("(fetches robots.txt only; never requests the candidate URL itself)")

    results = []
    for label, url in targets:
        try:
            results.append((label, check(label, url)))
        except Exception as exc:  # noqa: BLE001 - one bad host must not end the sweep
            print(f"\n{label}\n  ERROR: {exc}")
            results.append((label, None))

    print("\n" + "=" * 70)
    print("SUMMARY")
    for label, allowed in results:
        mark = {True: "ALLOWED", False: "BLOCKED", None: "ERROR  "}[allowed]
        print(f"  {mark}  {label}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
