"""Smoke fixture — seeded Gitleaks bait.

WARNING: This file is intentionally seeded with a synthetic AWS
access-key string. The string `AKIAIOSFODNN7EXAMPLE` is the
AWS-published documented test pattern; GitHub secret-scanning
push-protection allowlists it as a known-test-credential. Do NOT
replace with a real-shaped key — that would block the push to the
test repo and break every subsequent smoke run.

The smoke asserts that Gitleaks (running in-worker via
`GitleaksInWorkerRunner`) detects this pattern and produces a
finding with `category='security'` (or `'secret'` depending on
the curator's mapping).
"""

# ruff: noqa: S105 — synthetic test secret per fixture README.

# Smoke-fixture seeded secret. AWS-published documented test pattern.
AWS_SECRET = "AKIAIOSFODNN7EXAMPLE"  # noqa: S105

# Companion secret-key half. Also AWS-allowlisted.
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # noqa: S105


def get_aws_creds() -> tuple[str, str]:
    """Return the seeded credentials.

    Real consumers would read from an environment variable or a
    Vault path; this fixture's whole point is the literal string
    embedded above so Gitleaks fires on it.
    """
    return AWS_SECRET, AWS_SECRET_KEY
