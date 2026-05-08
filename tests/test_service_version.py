"""
Tests for SERVICE_VERSION constant change introduced in v1.4.3.

Scope: PR changed SERVICE_VERSION from "1.4.2" to "1.4.3" in src/main.py.
These tests verify the constant value and its propagation through the /health
endpoint, which is the primary public surface that exposes the version.
"""

import asyncio
import os
import sys

import httpx
import pytest

# Ensure src/ is importable when running pytest from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_VERSION = "1.4.3"
PREVIOUS_VERSION = "1.4.2"


def _import_main():
    """Return the src/main module (cached after first import)."""
    import main as m
    return m


def _get(path: str) -> httpx.Response:
    """Perform a synchronous GET against the FastAPI ASGI app."""
    m = _import_main()

    async def _fetch():
        transport = httpx.ASGITransport(app=m.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)

    return asyncio.run(_fetch())


# ---------------------------------------------------------------------------
# Direct constant tests
# ---------------------------------------------------------------------------

class TestServiceVersionConstant:
    """Verify the MODULE-LEVEL SERVICE_VERSION constant."""

    def test_service_version_is_expected(self):
        """SERVICE_VERSION must equal the v1.4.3 release string."""
        m = _import_main()
        assert m.SERVICE_VERSION == EXPECTED_VERSION

    def test_service_version_is_string(self):
        """SERVICE_VERSION must be a plain str, not an int or other type."""
        m = _import_main()
        assert isinstance(m.SERVICE_VERSION, str)

    def test_service_version_format(self):
        """SERVICE_VERSION must follow the MAJOR.MINOR.PATCH semver pattern."""
        m = _import_main()
        parts = m.SERVICE_VERSION.split(".")
        assert len(parts) == 3, f"Expected 3 version parts, got {len(parts)}"
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' is not a digit"

    def test_service_version_not_previous(self):
        """Regression: SERVICE_VERSION must NOT still be the old '1.4.2' value."""
        m = _import_main()
        assert m.SERVICE_VERSION != PREVIOUS_VERSION, (
            f"SERVICE_VERSION was not updated from the previous release ({PREVIOUS_VERSION})"
        )

    def test_service_version_patch_incremented(self):
        """The patch component must be strictly greater than in v1.4.2."""
        m = _import_main()
        major, minor, patch = (int(x) for x in m.SERVICE_VERSION.split("."))
        prev_major, prev_minor, prev_patch = (int(x) for x in PREVIOUS_VERSION.split("."))
        assert (major, minor, patch) > (prev_major, prev_minor, prev_patch), (
            "SERVICE_VERSION must be newer than the previous version"
        )


# ---------------------------------------------------------------------------
# /health endpoint tests (version propagation)
# ---------------------------------------------------------------------------

class TestHealthEndpointVersion:
    """Verify that /health propagates the updated SERVICE_VERSION."""

    def test_health_returns_200(self):
        """/health must respond with HTTP 200."""
        response = _get("/health")
        assert response.status_code == 200

    def test_health_version_field_present(self):
        """/health response must include a 'version' field."""
        body = _get("/health").json()
        assert "version" in body, "Missing 'version' key in /health response"

    def test_health_version_matches_constant(self):
        """/health 'version' must reflect SERVICE_VERSION = '1.4.3'."""
        assert _get("/health").json()["version"] == EXPECTED_VERSION

    def test_health_version_not_previous_release(self):
        """Regression: /health must NOT report the old version '1.4.2'."""
        assert _get("/health").json()["version"] != PREVIOUS_VERSION, (
            "/health is still reporting the pre-PR version"
        )

    def test_health_status_field(self):
        """/health 'status' field must be 'healthy' alongside the version."""
        assert _get("/health").json().get("status") == "healthy"
