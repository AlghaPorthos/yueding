# Hackathon development rig

## Outcome

Ship small, verifiable changes in the selected project. The rig is a delivery
system, not a chat room: every piece of work has an owner, an acceptance check,
and a durable queue record.

## Roles

- `orchestration-lead@hackathon-dev` (Codex, `gpt-6-astra`) owns intent parsing,
  decomposition, sequencing, risk decisions and final synthesis.
- `development-implementer@hackathon-dev` (Codex, `gpt-6-sol`) owns code and
  tests for one bounded slice.
- `development-verifier@hackathon-dev` (Codex, `gpt-6-sol`) independently runs
  checks against the exact candidate and reports evidence.
- `review-reviewer@hackathon-dev` (Claude, `glm-5.3`) provides a deep independent
  review for regressions, missing coverage, evidence boundaries and user-visible behavior.
- `review-fast-reviewer@hackathon-dev` (Claude, `glm-5.3-flash`) provides fast
  schema, API, regression and obvious security feedback while a slice is still cheap to change.

## Work protocol

1. Read `AGENTS.md`, `SPEC.md`, the active mission/slice and the relevant source
   before proposing implementation details.
2. The lead creates or claims a durable queue item with a concrete outcome,
   scope boundary and acceptance checks.
3. The implementer makes the smallest coherent change, preserves unrelated user
   work, and records the exact files and checks performed.
4. The verifier checks the exact diff or candidate, including the real user path
   when practical. A message is not a review; evidence belongs in the queue.
5. The fast Claude seat may review an early candidate for cheap feedback. The deep
   Claude seat reviews after the candidate is stable. Findings are actionable and
   tied to files, behavior or commands. The implementer resolves findings or the
   lead records why they are accepted.
6. The lead verifies the final candidate, updates the queue record and reports
   what changed, what passed and what remains unverified.

## Boundaries

Keep work local to the selected project. Do not publish, push, release, delete
data, or change credentials without a separate explicit instruction. Never put
secrets in queue bodies, logs, commits or reports. Use `rig send` for a prompt
or status message; use `rig queue create` and `rig queue handoff` for durable
work custody.

## Standard commands

```sh
rig whoami --json
rig queue list --owned --limit 1000
rig queue create --destination development-implementer@hackathon-dev \
  --body-file /tmp/hackathon-task.md
rig queue handoff <qitem-id> --to development-verifier@hackathon-dev \
  --body-file /tmp/hackathon-verification.md
rig queue list --all-rigs --full --limit 1000
```

The lead may use `rig send` for a short-lived instruction, but completion claims
must be backed by the queue, source changes and command output.
