# Team engineering guidelines

Smoke fixture — seeded **policy-engine** bait via
`.codemaster.yaml::knowledge.file_patterns`.

`TEAM_GUIDELINES.md` is **not** one of the policy engine's 15 default
guideline-file patterns (those are `CLAUDE.md`, `AGENTS.md`, etc.). The
seeded `.codemaster.yaml` adds `TEAM_GUIDELINES.md` to
`knowledge.file_patterns`, so the policy engine (A-1 discovery → A-2
rule extraction → A-3 scope resolution) should discover this file and
extract the rule below — which it would find ZERO of without the
`.codemaster.yaml` entry.

## Error handling

- Every outbound HTTP call MUST set an explicit timeout. A call with no
  timeout can hang a worker thread indefinitely under network
  partition. Reviewers should flag any `requests.get(...)` /
  `httpx.get(...)` without a `timeout=` argument.
