# `seeded-issues` — deterministic smoke fixture branch

These three Python files seed the smoke test repo (`inder1991/inventory-service`)
with **deterministically-detectable issues** so `tests/smoke/test_pr_to_review_happy_path.py`
can assert review *content* — not just "the workflow finished without an error."

## Expected findings (per smoke run)

| Source / tool | File | Finding | Severity |
|---|---|---|---|
| Gitleaks (in-worker) | `secrets_loader.py` | `AKIAIOSFODNN7EXAMPLE` (AWS-published synthetic key) | blocker |
| Gitleaks (in-worker) | `payment_service.ts` | synthetic GitHub PAT pattern (`ghp_...`) | blocker |
| Semgrep (K8s Job) | `payments_service.py` | f-string-concatenated SQL | issue / blocker |
| Semgrep (K8s Job) | `payment_service.ts` | `javascript.express.eval-detection` (eval on user input) | blocker |
| Ruff (in-worker) | `payments_service.py` | unused import (`F401`) | nit / suggestion |
| ESLint (in-worker) | `payment_service.ts` | `no-unused-vars` (`unusedHelper`) | suggestion |
| LLM reviewer | `null_check.py` | missing `None` guard before attribute access | issue / suggestion |
| LLM reviewer | `payment_service.ts` | missing input validation; info-disclosure via returned `config` | issue |
| LLM reviewer (adversarial) | `payments_service.py` | comment-injection bait + Cyrillic homoglyph | suggestion |

## Why this branch exists

Pre-fixture smokes used arbitrary `synchronize` events on whatever PR the operator had open. Diffs were trivial; there was no expected-finding-set to assert against. With this committed branch + the test App's auto-PR path (S15.X-github-test-app-harness), every smoke run produces the same set of categories — the smoke becomes a deterministic regression test for review *content*.

## Synthetic-key allowlist note

`AKIAIOSFODNN7EXAMPLE` is the AWS-published documented test pattern. GitHub secret-scanning push-protection allowlists it explicitly as a known-test-credential, so push to a public test repo does not trigger the protection. Do NOT replace with a real-shaped key — that would block the push.

## Bootstrap

```
python scripts/bootstrap_smoke_fixture_branch.py --repo inder1991/inventory-service
```

The script is idempotent — re-running over an existing `seeded-issues` branch fast-forwards from the local fixture content. It does NOT delete the branch on subsequent runs (operators rebase manually if `main` shifts under it).

## Per-run hygiene

`tests/smoke/_harness.py::GitHubTestApp.cleanup_pr` closes the PR + deletes the *per-run* head branch after a successful smoke run. The `seeded-issues` fixture branch persists; only the `main`-derived per-run branch is removed.

## Adversarial corpus delta

The comment-injection in `payments_service.py` is also recorded as `tests/corpora/prompt_injection/0057-fixture-comment-injection.yaml` so the adversarial-corpus detection gate (≥ 95%) covers the same pattern that lives in the fixture.
