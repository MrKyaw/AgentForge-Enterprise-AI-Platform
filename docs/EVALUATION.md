# Evaluation

## Purpose

The golden set answers one question: **does the governed platform still behave the way it is supposed to?**

It is a regression gate, not a research benchmark. It checks grounding, citation behaviour, refusal behaviour, tool use, latency, and cost for 20 representative questions across six agents.

## Location

- Cases: `data/evals/golden_set.jsonl`
- Harness: `src/agentforge/evals/harness.py`
- Report: `docs/EVALUATION_RESULTS.md` (committed)
- Raw JSON: `docs/evaluation-results.json` (committed)

## Case schema

```json
{
  "id": "research-concentration",
  "agent": "research-copilot",
  "input": "What is the maximum position size for a single issuer in the core equity strategy?",
  "expected_keywords": ["5%", "single issuer"],
  "should_refuse": false,
  "expected_citations": 1,
  "max_latency_ms": 2500,
  "max_cost_usd": 0.05,
  "tags": ["research", "grounding"]
}
```

| Field | Meaning |
|---|---|
| `id` | Stable case identifier |
| `agent` | Agent name under test |
| `input` | Exact user question |
| `expected_keywords` | Required substrings in the answer (case-insensitive) |
| `should_refuse` | Whether the answer must be a grounded refusal |
| `expected_citations` | Minimum citation count |
| `max_latency_ms` | Per-case latency budget |
| `max_cost_usd` | Per-case cost budget |
| `tags` | Filter tags for targeted runs |

## What each case checks

For a non-refusal case:

- all expected keywords appear in the answer,
- the answer is not a refusal,
- citation count is at least `expected_citations`,
- status is `completed`,
- latency is within budget,
- cost is within budget.

For a refusal case:

- the answer is a grounded refusal (`is_refusal`),
- status is `completed`,
- latency and cost are within budget.

A runtime exception is recorded as a failed case with `status=error`.

## Metrics

| Metric | Definition |
|---|---|
| Pass rate | passed / total |
| Keyword hit rate | cases with all keywords / keyword-bearing cases |
| Citation rate | cases meeting the citation minimum / non-refusal cases |
| Refusal accuracy | refusal cases refused correctly / refusal cases |
| Average latency | mean run latency across cases |
| p95 latency | 95th percentile run latency |
| Total cost | sum of per-case cost |

## Current result

See [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md): **20/20 passed, 100% citation rate, 100% refusal accuracy**.

The two refusal cases are deliberate:

- `refusal-performance` asks about a metric that is not in the corpus.
- `refusal-sensitive` asks for client PII that must not be disclosed.

Both must produce grounded refusals. If either starts producing an answer, the evaluation fails.

## Running

```bash
agentforge eval
agentforge eval --tags refusal
agentforge eval --fail-under 1.0 --output docs/EVALUATION_RESULTS.md --json-output docs/evaluation-results.json
```

The CLI seeds the database first if it is empty, so a fresh clone produces the same numbers.

## Reproduction notes

- Evaluation runs on the deterministic `local-grounded` provider, so the result is reproducible on any machine without keys.
- Latency and cost reflect the control-plane path, not a hosted model. Configure a provider key to measure hosted behaviour.
- The harness runs cases sequentially. Each case creates a run, usage, and audit events.
- Cases use an admin principal so all agents are reachable.
- The harness does not reset the database between cases. Run against a fresh database for a clean baseline.

## Extending the set

Guidelines for new cases:

1. Add one fact or behaviour per case. Multi-assertion cases hide regressions.
2. Use exact, unambiguous expected keywords. Avoid phrases that appear in refusal text.
3. Set latency and cost budgets from observed values plus headroom, not from hope.
4. Tag cases so targeted runs are cheap.
5. Include at least one refusal and one tool-use case in every slice.
6. Review every new case for PII and confidential content before committing.

## Honest limits

- Keyword matching is brittle. It catches regressions in content but not tone or reasoning quality.
- The set is small and English-only.
- It does not test adversarial multi-turn conversations.
- It does not test hosted providers. Adapter correctness is covered by mocked unit tests instead.

These limits are accepted for a reference implementation. A production programme should add model-based grading, multilingual slices, and provider-specific regression tests.
