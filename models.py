"""Smoke fixture — seeded path_instructions (.codemaster.yaml) bait.

This file carries a bug that ONLY the
`.codemaster.yaml::path_instructions` Django rule surfaces:

    Every `model.save()` MUST be preceded by `model.full_clean()`.

`save_order` below calls `.save()` with no preceding `.full_clean()`.
No linter (Ruff/ESLint/Gitleaks/Semgrep) flags this, and a default LLM
review without the team rule would not reliably call it out. The seeded
`.codemaster.yaml` injects the rule via `path_instructions` for
`**/*.py`, so the reviewer should produce a finding on this file — the
smoke's proof that path_instructions reach the model and change its
output (asserted by tests/smoke/_config_assertions.py).

Deliberately a Django-shaped stub (no real Django dependency) so the
fixture stays import-light; the reviewer reasons over the source text.
"""

from __future__ import annotations


class _Model:
    """Minimal Django-model stand-in for the fixture."""

    def full_clean(self) -> None:
        """Run model validators (Django's pre-save validation hook)."""

    def save(self) -> None:
        """Persist the row."""


class Order(_Model):
    def __init__(self, total: int) -> None:
        self.total = total


def save_order(total: int) -> Order:
    """Create + persist an Order.

    BUG (intentional, smoke fixture for path_instructions): this calls
    ``order.save()`` WITHOUT a preceding ``order.full_clean()``, so
    validation is skipped before the write. The team's Django rule in
    ``.codemaster.yaml::path_instructions`` requires full_clean() first;
    the reviewer must flag the missing call.
    """
    order = Order(total=total)
    order.save()  # path_instructions bait: no full_clean() before save()
    return order
