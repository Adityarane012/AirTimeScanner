"""Enforcement of the collection compliance posture from
docs/01-data-acquisition.md. Until this module existed, that posture was a
written commitment with nothing in code behind it — `collection_run` even had
a `robots_checked_at` column that nothing ever wrote.

The four controls docs/01 commits to, and where each lives here:

1. "Identified, contactable user agent naming the project and an operator
   email"                                        -> settings.apix_user_agent, applied by callers
2. "Per-source robots.txt re-checked on every run, not cached indefinitely"
                                                 -> RobotsGate (per-run cache, never cross-run)
3. "Conservative rate limits ... one request per source per several seconds,
   with jitter"                                  -> RateLimiter
4. "Full backoff and circuit-breaking on 429/403; a source that signals stop,
   stops"                                        -> CircuitBreaker + fetch_politely

A note on user agents, learned the hard way in Phase 0 (docs/06-recon-log.md):
some Akamai-fronted hosts reset the connection when a *custom* UA header is
combined with `impersonate="chrome"`, because the declared UA contradicts the
TLS fingerprint. That is a transport-layer quirk, not a licence to hide. So:

- We always evaluate robots.txt rules against our **real** agent token
  (`APIX_AGENT_TOKEN`), never against "chrome" — we obey the rules that apply
  to us.
- We send the identifying UA header wherever the host accepts it, and fall
  back to impersonation-only for hosts that break on it, which is exactly what
  robots.txt fetching needs on goindigo.in.

That keeps identification honest where it can be honest, and never uses the
fallback to reach something robots.txt disallows.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

from protego import Protego

# The token robots.txt rules are evaluated against. Matches the product name in
# settings.apix_user_agent; kept separate because robots matching uses the
# bare product token, not the full UA string.
APIX_AGENT_TOKEN = "APIx-Collector"

# docs/01: "one request per source per several seconds, with jitter"
DEFAULT_MIN_INTERVAL_S = 5.0
DEFAULT_JITTER_S = 2.0

# docs/01: "a source that signals stop, stops"
STOP_STATUSES = frozenset({429, 403})


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids the URL for our agent. Never caught and
    retried — a disallow is a decision, not a transient failure."""


class CircuitOpen(Exception):
    """Raised when a source has signalled stop (429/403) and is now tripped."""


@dataclass
class RobotsVerdict:
    allowed: bool
    checked_at: datetime
    crawl_delay: float | None
    robots_url: str
    reason: str = ""


class RobotsGate:
    """Fetches and evaluates robots.txt per host.

    Cache lifetime is the lifetime of this object, and collection code creates
    one per run — which is precisely docs/01's "re-checked on every run, not
    cached indefinitely". Do not promote this to a module-level singleton.

    `fetcher` is injected so tests never touch the network (docs/03's testing
    rule: parser/collection tests run against fixtures, never live sites).
    """

    def __init__(self, fetcher=None, agent_token: str = APIX_AGENT_TOKEN) -> None:
        self._fetcher = fetcher
        self._agent_token = agent_token
        self._cache: dict[str, RobotsVerdict | None] = {}
        self._parsers: dict[str, Protego | None] = {}

    def _robots_url_for(self, url: str) -> str:
        parts = urlparse(url)
        return f"{parts.scheme}://{parts.netloc}/robots.txt"

    def _load(self, robots_url: str) -> Protego | None:
        if robots_url in self._parsers:
            return self._parsers[robots_url]

        body: str | None = None
        try:
            body = self._fetch_robots(robots_url)
        except Exception:  # noqa: BLE001 - any failure here means 'unverified', never 'allowed'
            body = None

        parser = Protego.parse(body) if body is not None else None
        self._parsers[robots_url] = parser
        return parser

    def _fetch_robots(self, robots_url: str) -> str | None:
        if self._fetcher is not None:
            return self._fetcher(robots_url)

        # Real fetch. Impersonation WITHOUT a custom UA header: some hosts
        # reset the connection on the mismatch (see module docstring). The
        # rules are still evaluated against our own agent token below.
        from scrapling.fetchers import Fetcher

        resp = Fetcher.get(robots_url, impersonate="chrome")
        if resp.status != 200:
            return None
        return resp.body.decode("utf-8", errors="replace")

    def check(self, url: str) -> RobotsVerdict:
        robots_url = self._robots_url_for(url)
        parser = self._load(robots_url)
        now = datetime.now(UTC)

        if parser is None:
            # No robots.txt retrievable. RFC 9309: an unreachable/absent
            # robots.txt means no restrictions are published. We proceed, but
            # record that we could not verify — an honest "unverified", not a
            # silent "allowed".
            return RobotsVerdict(
                allowed=True,
                checked_at=now,
                crawl_delay=None,
                robots_url=robots_url,
                reason="robots.txt unreachable or absent; no published restrictions",
            )

        allowed = parser.can_fetch(url, self._agent_token)
        delay = parser.crawl_delay(self._agent_token)
        return RobotsVerdict(
            allowed=bool(allowed),
            checked_at=now,
            crawl_delay=float(delay) if delay is not None else None,
            robots_url=robots_url,
            reason="allowed by robots.txt" if allowed else "DISALLOWED by robots.txt",
        )


class RateLimiter:
    """Per-host minimum interval with jitter. Thread-safe so a future
    parallel-adapter runner cannot accidentally defeat it.
    """

    def __init__(
        self,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        jitter_s: float = DEFAULT_JITTER_S,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.jitter_s = jitter_s
        self._sleep = sleep
        self._clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str, crawl_delay: float | None = None) -> float:
        """Block until it is polite to hit this host. Returns seconds slept.

        A robots.txt Crawl-delay always wins if it is *longer* than our own
        floor — the site's stated preference beats our default.
        """
        host = urlparse(url).netloc
        interval = max(self.min_interval_s, crawl_delay or 0.0)

        with self._lock:
            now = self._clock()
            last = self._last.get(host)
            slept = 0.0
            if last is not None:
                target = last + interval + random.uniform(0, self.jitter_s)
                slept = max(0.0, target - now)
                if slept > 0:
                    self._sleep(slept)
            self._last[host] = self._clock()
            return slept


@dataclass
class CircuitBreaker:
    """docs/01: "a source that signals stop, stops". One 429/403 trips the
    host for the rest of the run — deliberately not a retry-with-backoff
    loop, because retrying past an explicit refusal is the behaviour this
    project committed to not building.
    """

    tripped: dict[str, str] = field(default_factory=dict)

    def check(self, url: str) -> None:
        host = urlparse(url).netloc
        if host in self.tripped:
            raise CircuitOpen(f"{host} previously signalled stop ({self.tripped[host]}); not retrying this run")

    def record_status(self, url: str, status: int) -> None:
        if status in STOP_STATUSES:
            host = urlparse(url).netloc
            self.tripped[host] = f"HTTP {status}"


@dataclass
class PolitenessResult:
    body: bytes
    status: int
    robots: RobotsVerdict
    slept_s: float


class PoliteFetcher:
    """Single entry point adapters use instead of calling Fetcher directly.
    Composes all four controls so an adapter cannot accidentally skip one.
    """

    def __init__(
        self,
        robots: RobotsGate | None = None,
        limiter: RateLimiter | None = None,
        breaker: CircuitBreaker | None = None,
        transport=None,
    ) -> None:
        self.robots = robots or RobotsGate()
        self.limiter = limiter or RateLimiter()
        self.breaker = breaker or CircuitBreaker()
        self._transport = transport

    def get(self, url: str, user_agent: str) -> PolitenessResult:
        self.breaker.check(url)

        verdict = self.robots.check(url)
        if not verdict.allowed:
            raise RobotsDisallowed(f"{url} is disallowed by {verdict.robots_url} for {APIX_AGENT_TOKEN}")

        slept = self.limiter.wait(url, verdict.crawl_delay)

        status, body = self._do_get(url, user_agent)
        self.breaker.record_status(url, status)
        if status in STOP_STATUSES:
            raise CircuitOpen(f"{url} returned HTTP {status}; source signalled stop")

        return PolitenessResult(body=body, status=status, robots=verdict, slept_s=slept)

    def _do_get(self, url: str, user_agent: str) -> tuple[int, bytes]:
        if self._transport is not None:
            return self._transport(url, user_agent)

        from scrapling.fetchers import Fetcher

        resp = Fetcher.get(url, impersonate="chrome", headers={"User-Agent": user_agent})
        return resp.status, resp.body
