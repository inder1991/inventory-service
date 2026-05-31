// tests/smoke/fixtures/seeded-issues/payment_service.ts
//
// Phase A fixture extension (2026-05-16, static-analysis coverage gap fix).
//
// This file owns the TypeScript Tier-1 + Tier-2 baits. Secret detection
// (Gitleaks) is demonstrated solely by `secrets_loader.py` — the previous
// duplicate `ghp_...` PAT here was removed in the 2026-05-31 SDET dedup so
// each finding maps to one distinct product feature.
//
// Expected findings (the smoke chain asserts each):
//
//   - ESLint:  `no-unused-vars` on `unusedHelper`  (TS static analysis)
//   - Semgrep: javascript.express.eval-detection   (runtime eval on user input)
//   - LLM:     missing input validation before eval; information-
//              disclosure risk via returned `config`

import express from "express";

// eslint should flag this as `no-unused-vars`.
const unusedHelper = (x: number): number => x * 2;

export function processPayment(req: express.Request): unknown {
  // semgrep `javascript.express.eval-detection` should flag this.
  // The LLM should additionally flag: no input validation; returning
  // the parsed config to the caller leaks an attacker-controlled value.
  const config = eval(req.body.config);
  return config;
}
