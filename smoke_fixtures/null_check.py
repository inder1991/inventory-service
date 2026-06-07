"""Smoke fixture — seeded LLM-reviewer null-deref bait.

Targets the model's null-handling reasoning. Linters generally
don't catch this category (Ruff's F-codes are import/syntax/style;
Gitleaks is secrets; Semgrep's default ruleset focuses on
security patterns, not unconditional attribute access). The LLM
reviewer should produce a finding with `category='correctness'`
flagging the missing `if user is None` guard before
`user.email` is accessed.

The bait is intentionally tight: small function, single bug,
no other distractors. Re-running the smoke 3× should produce a
finding here on every run (LLM nondeterminism is bounded by
S20.SMOKE.A's ±1-finding tolerance band — zero LLM findings
across all 3 runs is a regression).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _User:
    user_id: str
    email: str


class _UserStore:
    """Stub user-store; production implementation would talk to
    the real DB. The lookup *can* return None — that's the whole
    bug class this fixture exercises."""

    def find(self, user_id: str) -> _User | None:
        if not user_id:
            return None
        # Real implementation would hit Postgres; the bait is the
        # caller below, not this stub.
        return _User(user_id=user_id, email=f"{user_id}@example.com")


_store = _UserStore()


def get_user_email(user_id: str) -> str:
    """Look up a user and return their email.

    BUG (intentional, smoke fixture): `_store.find(user_id)` can
    return `None` for empty / unknown user-id, but the next line
    accesses `user.email` unconditionally. Reviewer must flag the
    missing `is None` guard before it becomes an `AttributeError`
    in production.
    """
    user = _store.find(user_id)
    return user.email
