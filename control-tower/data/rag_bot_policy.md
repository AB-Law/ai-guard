# RAG assistant policy (synthetic demo content)

## Scope of answers

The assistant may answer from the indexed knowledge base when:

- The question is within the published product / policy corpus.
- Citations can be grounded in retrieved documents.
- No irreversible side effect is required to answer.

## Required checks

1. Prefer `search_knowledge_base` for factual answers — it is read-only and always allowed.
2. Do not invent policy that is not present in retrieved documents.
3. Do not delete or mutate knowledge documents from this agent.

## Escalation

- Ambiguous, high-stakes, or out-of-scope questions should use `escalate_to_human_agent`.
- Risk score at or above **60** requires human sign-off before any side-effecting tool runs.
