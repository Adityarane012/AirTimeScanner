"""Tests for the compliance controls docs/01 commits this project to.

All network access is injected/stubbed — per docs/03's testing rule, these
never touch a live site. That matters doubly here: a test suite that hit real
airline sites to check politeness would itself be impolite.
"""

import pytest

from apix.acquisition.compliance import (
    CircuitBreaker,
    CircuitOpen,
    PoliteFetcher,
    RateLimiter,
    RobotsDisallowed,
    RobotsGate,
)

ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"
ROBOTS_BLOCK_DAM = "User-agent: *\nDisallow: /content/dam\nDisallow: /dam\n"
ROBOTS_BLOCK_US_SPECIFICALLY = "User-agent: APIx-Collector\nDisallow: /\n\nUser-agent: *\nDisallow:\n"
ROBOTS_WITH_DELAY = "User-agent: *\nCrawl-delay: 20\nDisallow:\n"


def gate_for(body):
    """RobotsGate whose robots.txt fetch is stubbed to `body` (None = absent)."""
    return RobotsGate(fetcher=lambda url: body)


# --- robots.txt enforcement -------------------------------------------------

def test_allows_url_not_disallowed():
    v = gate_for(ROBOTS_ALLOW_ALL).check("https://x.example/tariff.pdf")
    assert v.allowed is True
    assert v.checked_at is not None


def test_blocks_disallowed_path():
    """The real Air India Express case: its tariff PDF sits under /content/dam,
    which its own robots.txt disallows (docs/06-recon-log.md)."""
    v = gate_for(ROBOTS_BLOCK_DAM).check("https://x.example/content/dam/docs/tariff.pdf")
    assert v.allowed is False
    assert "DISALLOWED" in v.reason


def test_allows_sibling_path_outside_the_disallowed_subtree():
    """The real IndiGo case: /content/dam/goindigo/... is blocked but the
    tariff sits at /content/dam/s6web/... — must not over-block."""
    body = "User-agent: *\nDisallow: /content/dam/goindigo/\n"
    v = gate_for(body).check("https://x.example/content/dam/s6web/in/en/assets/documents/t.pdf")
    assert v.allowed is True


def test_rules_are_evaluated_against_our_own_agent_token_not_a_browser():
    """We must obey rules aimed at us specifically, never evade them by
    presenting as a browser."""
    v = gate_for(ROBOTS_BLOCK_US_SPECIFICALLY).check("https://x.example/anything")
    assert v.allowed is False


def test_absent_robots_is_recorded_as_unverified_not_silently_allowed():
    v = gate_for(None).check("https://x.example/thing")
    assert v.allowed is True
    assert "unreachable or absent" in v.reason


def test_crawl_delay_is_read():
    v = gate_for(ROBOTS_WITH_DELAY).check("https://x.example/thing")
    assert v.crawl_delay == 20.0


def test_robots_is_fetched_once_per_host_within_a_run():
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return ROBOTS_ALLOW_ALL

    gate = RobotsGate(fetcher=counting_fetch)
    gate.check("https://x.example/a")
    gate.check("https://x.example/b")
    gate.check("https://other.example/c")
    assert len(calls) == 2  # one per host, not per URL


# --- rate limiting ----------------------------------------------------------

def test_first_request_to_a_host_does_not_sleep():
    slept = []
    limiter = RateLimiter(sleep=slept.append, clock=lambda: 0.0)
    assert limiter.wait("https://x.example/a") == 0.0
    assert slept == []


def test_second_request_to_same_host_waits_at_least_the_min_interval():
    slept = []
    t = iter([0.0, 0.0, 0.1, 0.1])
    limiter = RateLimiter(min_interval_s=5.0, jitter_s=0.0, sleep=slept.append, clock=lambda: next(t))
    limiter.wait("https://x.example/a")
    limiter.wait("https://x.example/b")
    assert slept and slept[0] >= 4.8


def test_different_hosts_do_not_block_each_other():
    slept = []
    t = iter([0.0, 0.0, 0.1, 0.1])
    limiter = RateLimiter(min_interval_s=5.0, jitter_s=0.0, sleep=slept.append, clock=lambda: next(t))
    limiter.wait("https://a.example/x")
    limiter.wait("https://b.example/x")
    assert slept == []


def test_robots_crawl_delay_overrides_our_floor_when_longer():
    slept = []
    t = iter([0.0, 0.0, 0.0, 0.0])
    limiter = RateLimiter(min_interval_s=5.0, jitter_s=0.0, sleep=slept.append, clock=lambda: next(t))
    limiter.wait("https://x.example/a")
    limiter.wait("https://x.example/b", crawl_delay=30.0)
    assert slept and slept[0] >= 29.0


# --- circuit breaking -------------------------------------------------------

@pytest.mark.parametrize("status", [429, 403])
def test_stop_signal_trips_the_breaker(status):
    b = CircuitBreaker()
    b.record_status("https://x.example/a", status)
    with pytest.raises(CircuitOpen):
        b.check("https://x.example/b")


def test_normal_status_does_not_trip():
    b = CircuitBreaker()
    b.record_status("https://x.example/a", 200)
    b.check("https://x.example/b")  # must not raise


# --- the composed fetcher ---------------------------------------------------

def test_polite_fetcher_refuses_disallowed_url_without_fetching():
    fetched = []

    def transport(url, ua):
        fetched.append(url)
        return 200, b"should never happen"

    pf = PoliteFetcher(
        robots=gate_for(ROBOTS_BLOCK_DAM),
        limiter=RateLimiter(sleep=lambda s: None, clock=lambda: 0.0),
        transport=transport,
    )
    with pytest.raises(RobotsDisallowed):
        pf.get("https://x.example/content/dam/t.pdf", user_agent="APIx-Collector/0.1")
    assert fetched == []  # the critical assertion: never hit the wire


def test_polite_fetcher_returns_body_and_verdict_on_allowed_url():
    pf = PoliteFetcher(
        robots=gate_for(ROBOTS_ALLOW_ALL),
        limiter=RateLimiter(sleep=lambda s: None, clock=lambda: 0.0),
        transport=lambda url, ua: (200, b"%PDF-1.4 data"),
    )
    result = pf.get("https://x.example/t.pdf", user_agent="APIx-Collector/0.1")
    assert result.body == b"%PDF-1.4 data"
    assert result.status == 200
    assert result.robots.allowed is True
    assert result.robots.checked_at is not None


def test_polite_fetcher_raises_and_trips_on_stop_status():
    pf = PoliteFetcher(
        robots=gate_for(ROBOTS_ALLOW_ALL),
        limiter=RateLimiter(sleep=lambda s: None, clock=lambda: 0.0),
        transport=lambda url, ua: (429, b""),
    )
    with pytest.raises(CircuitOpen):
        pf.get("https://x.example/t.pdf", user_agent="APIx-Collector/0.1")
    # and the host stays tripped for the rest of the run
    with pytest.raises(CircuitOpen):
        pf.get("https://x.example/other.pdf", user_agent="APIx-Collector/0.1")


def test_user_agent_is_passed_through_to_the_transport():
    seen = {}

    def transport(url, ua):
        seen["ua"] = ua
        return 200, b"ok"

    pf = PoliteFetcher(
        robots=gate_for(ROBOTS_ALLOW_ALL),
        limiter=RateLimiter(sleep=lambda s: None, clock=lambda: 0.0),
        transport=transport,
    )
    pf.get("https://x.example/t.pdf", user_agent="APIx-Collector/0.1 (+mailto:x@y.z)")
    assert "APIx-Collector" in seen["ua"]
    assert "mailto:" in seen["ua"]


# ---------------------------------------------------------------------------
# Identification under a hostile TLS fingerprint check
#
# Verified live on airindia.com: the identifying User-Agent resets the
# connection every time, dropping it succeeds every time, and a plain
# non-impersonated request with the honest UA also resets. The edge requires a
# consistent fingerprint. The response must be to keep identifying ourselves by
# another standards-defined route, never to go anonymous.
# ---------------------------------------------------------------------------

from apix.acquisition import compliance as _compliance
from apix.acquisition.compliance import (
    _is_fingerprint_reset,
    identifying_headers,
)

UA = "APIx-Collector/0.1 (+mailto:ops@example.invalid; research project)"


def test_identifying_headers_carry_contact_even_without_a_user_agent():
    """docs/01 asks for an identified, contactable agent. Contactability is the
    substance of that, and it must survive dropping the UA header."""
    full = identifying_headers(UA, with_user_agent=True)
    reduced = identifying_headers(UA, with_user_agent=False)

    assert full["User-Agent"] == UA
    assert "User-Agent" not in reduced

    # RFC 9110 From: the mailbox of the human controlling the agent.
    assert full["From"] == "ops@example.invalid"
    assert reduced["From"] == "ops@example.invalid"
    assert reduced["X-Crawler-Contact"] == UA


def test_contact_email_has_a_single_source_of_truth():
    """Parsed out of the configured UA so the address cannot drift between the
    User-Agent and From headers."""
    headers = identifying_headers("APIx/9 (+mailto:someone@else.invalid)", with_user_agent=True)
    assert headers["From"] == "someone@else.invalid"


def test_headers_omit_from_when_the_agent_declares_no_mailbox():
    headers = identifying_headers("APIx-Collector/0.1", with_user_agent=True)
    assert "From" not in headers
    assert headers["X-Crawler-Contact"] == "APIx-Collector/0.1"


def test_fingerprint_reset_is_recognised():
    reset = Exception("Failed to perform, curl: (92) HTTP/2 stream 5 reset by server (INTERNAL_ERROR)")
    assert _is_fingerprint_reset(reset) is True
    assert _is_fingerprint_reset(Exception("404 Not Found")) is False


def test_polite_fetcher_retries_without_the_user_agent_on_a_fingerprint_reset(monkeypatch):
    calls = []

    class FakeResponse:
        status = 200
        body = b"%PDF-fake"

    class FakeFetcher:
        @staticmethod
        def get(url, **kwargs):
            headers = kwargs.get("headers", {})
            calls.append(headers)
            if "User-Agent" in headers:
                raise RuntimeError("Failed to perform, curl: (92) HTTP/2 stream 5 reset by server")
            return FakeResponse()

    import scrapling.fetchers

    monkeypatch.setattr(scrapling.fetchers, "Fetcher", FakeFetcher)

    fetcher = _compliance.PoliteFetcher(
        robots=_compliance.RobotsGate(fetcher=lambda _u: "User-agent: *\nDisallow: /nope\n"),
        limiter=_compliance.RateLimiter(min_interval_s=0, jitter_s=0),
    )
    result = fetcher.get("https://host.invalid/tariff.pdf", UA)

    assert result.status == 200
    assert len(calls) == 2, "should try the identifying UA first, then fall back"
    assert "User-Agent" in calls[0]
    assert "User-Agent" not in calls[1]
    # The fallback is still identified -- that is the whole point.
    assert calls[1]["From"] == "ops@example.invalid"
    assert fetcher.identified_via == "from-header"


def test_a_non_fingerprint_error_is_not_retried_or_swallowed(monkeypatch):
    class FakeFetcher:
        @staticmethod
        def get(url, **kwargs):
            raise RuntimeError("500 Internal Server Error")

    import scrapling.fetchers

    monkeypatch.setattr(scrapling.fetchers, "Fetcher", FakeFetcher)

    fetcher = _compliance.PoliteFetcher(
        robots=_compliance.RobotsGate(fetcher=lambda _u: "User-agent: *\n"),
        limiter=_compliance.RateLimiter(min_interval_s=0, jitter_s=0),
    )
    with pytest.raises(RuntimeError, match="500"):
        fetcher.get("https://host.invalid/x.pdf", UA)


def test_the_fallback_never_reaches_a_disallowed_url(monkeypatch):
    """The robots gate runs before any transport attempt, so the fallback
    cannot become a way around a disallow."""
    attempted = []

    class FakeFetcher:
        @staticmethod
        def get(url, **kwargs):
            attempted.append(url)
            raise AssertionError("transport must never be reached for a disallowed URL")

    import scrapling.fetchers

    monkeypatch.setattr(scrapling.fetchers, "Fetcher", FakeFetcher)

    fetcher = _compliance.PoliteFetcher(
        robots=_compliance.RobotsGate(fetcher=lambda _u: "User-agent: *\nDisallow: *.pdf\n"),
        limiter=_compliance.RateLimiter(min_interval_s=0, jitter_s=0),
    )
    with pytest.raises(_compliance.RobotsDisallowed):
        fetcher.get("https://host.invalid/tariff.pdf", UA)
    assert attempted == []
