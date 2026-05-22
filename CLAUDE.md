# inventory-service review standards

Repo-wide rules consumed by codemaster's policy engine (Subsystem A).
Each section's bullets become one extracted rule per A-2's
heading-aware parser. Categories are inferred by
`codemaster.policy.rule_classifier`.

## Security

* Never commit credentials to source. Hardcoded API keys, GitHub Personal Access Tokens, AWS access tokens (AKIA…), and database passwords are blockers — rotate them at the issuing provider immediately and load from environment variables (in dev) or HashiCorp Vault (in production) at runtime.
* `eval()` and `exec()` on caller-supplied input are forbidden. They open RCE; replace with `json.loads` plus a schema validator, or `ast.literal_eval` for trusted Python-literal payloads only.
* SQL queries MUST use parameterised statements. f-string interpolation of user input into SQL is SQL injection — even when the variable looks "innocent."
* PII handling: email addresses, full names, phone numbers, and street addresses MUST be redacted before logging. Either pass through a redaction filter or hash at logging time.

## Correctness

* Functions returning `Optional[T]` (or any nullable type) must be guarded before attribute access. Unconditional `.method()` on a value of type `Optional[T]` is a blocker bug.
* Identifier names containing non-ASCII / non-Latin characters (Cyrillic homoglyphs, Greek lookalikes) are blockers. They create invisible mismatches between definition and usage, and module-level `from X import name` silently imports the wrong identifier.
* Falsy-only guards on string inputs (`if value:` for required strings) are a correctness hazard — empty string vs `None` vs missing-key are distinct cases. Use `if value is None:` or `if not value.strip():` explicitly.

## Test discipline

* Every bug fix must arrive with a regression test that fails before the fix and passes after. Commits that change behaviour without a corresponding test are blockers.
* Test stubs of code that handles None / optional cases MUST cover the None branch. A stub that only exercises the happy path lies to its readers about coverage.
