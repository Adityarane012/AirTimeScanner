"""The preflight names the host so a wrong one is diagnosable — and never the
password, because it prints into a public GitHub annotation.

The stand-in password below is one of check_secrets.py's known placeholders:
a realistic-looking fake would be blocked from this public repo by the very
guard that exists to catch a real one.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from preflight_db import describe_target

POOLER = "postgresql+psycopg://postgres.abcdef:your-password@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
DIRECT = "postgresql+psycopg://postgres:your-password@db.abcdef.supabase.co:5432/postgres"


def test_the_host_and_user_are_named():
    described = describe_target(POOLER)
    assert "aws-0-ap-south-1.pooler.supabase.com:5432" in described
    assert "postgres.abcdef" in described


def test_the_password_is_never_printed():
    for url in (POOLER, DIRECT):
        assert "your-password" not in describe_target(url)


def test_a_malformed_url_does_not_leak_its_contents():
    """If it cannot be parsed it cannot be redacted field by field, so none of
    it is printed."""
    described = describe_target("not-a-url://@@@:your-password@@@")
    assert "your-password" not in described
    assert described == "<unparseable DATABASE_URL>"
