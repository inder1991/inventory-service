"""Smoke fixture — seeded path_filters EXCLUSION bait.

This file lives under ``generated/`` and the seeded
``.codemaster.yaml::path_filters`` carves that directory out:

    path_filters:
      - "**"
      - "!**/generated/**"

It is INTENTIONALLY full of bait that WOULD be flagged if reviewed:
  * an unused import (Ruff F401),
  * a hardcoded AWS test key (Gitleaks),
  * a `.save()` without `.full_clean()` (the path_instructions rule).

The smoke proves the path_filters sub-feature by asserting this file
appears in the PR diff (so it WAS pushed) but receives ZERO findings —
because path_filters excluded it from the review set before chunking.
If path_filters regressed (file reviewed), these baits would fire and
the negative assertion in tests/smoke/_config_assertions.py would catch
it.

Generated code is the canonical real-world path_filters use case:
machine-emitted, not worth reviewing, noise if reviewed.
"""

import json  # would be Ruff F401 if this file were reviewed

# would be a Gitleaks secret finding if this file were reviewed.
GENERATED_KEY = "AKIAIOSFODNN7EXAMPLE"  # noqa: S105


class _Pb2Model:
    def full_clean(self) -> None: ...
    def save(self) -> None: ...


def _emit() -> str:
    m = _Pb2Model()
    m.save()  # would trip the path_instructions full_clean() rule
    return json.dumps({"generated": True})
