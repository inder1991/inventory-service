// tests/smoke/fixtures/seeded-issues/payment_service.ts
//
// Phase A fixture extension (2026-05-16, static-analysis coverage gap fix).
//
// Expected findings per Tier 1 source (the smoke chain asserts each):
//
//   - ESLint:   `no-unused-vars` on `unusedHelper`  (line 14)
//   - Gitleaks: synthetic GitHub PAT pattern        (line 9)
//   - Semgrep:  javascript.express.eval-detection   (line 21, runtime eval on user input)
//
// Expected Tier 2 LLM finding (complementary; not predictable but
// reasonable to expect on this code):
//
//   - LLM: missing input validation before eval call;
//          information-disclosure risk via returned `config`
//
// Synthetic-key disclaimer: this is a fixture file. The token below
// is intentionally a non-functional synthetic per the seeded-issues
// fixture conventions (see README.md). Gitleaks will flag it — that
// is the test.

import express from "express";

// gitleaks should flag this; pragma-allowlist is for the OUR codebase
// lint, not for the bot we're testing.
const GH_PAT = "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa0";  // pragma: allowlist secret

// eslint should flag this as `no-unused-vars`.
const unusedHelper = (x: number): number => x * 2;

export function processPayment(req: express.Request): unknown {
  // semgrep `javascript.express.eval-detection` should flag this.
  // The LLM should additionally flag: no input validation; returning
  // the parsed config to the caller leaks an attacker-controlled value.
  const config = eval(req.body.config);
  return config;
}

export const apiToken = GH_PAT;
