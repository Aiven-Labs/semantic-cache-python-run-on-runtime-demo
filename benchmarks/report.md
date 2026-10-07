# Classifier comparison

Run on 2026-10-07: 93 labeled messages, one at a time with no conversation history. Every model chooses between the same six kinds: chat, search, repo, analysis, other and out_of_scope. Prices are the list prices in `settings.toml`.

## Summary

| Model | In-scope accuracy | All-message accuracy | Off-topic caught | Wrongly refused | Mean latency | p95 | Tokens in / out | $ per 1,000 calls |
|---|---|---|---|---|---|---|---|---|
| jev-latest | 95.1% (4 wrong) | 95.7% | 12/12 | 2 | 0.23 s | 0.40 s | 552 / 61.3 | $0.023 |
| qwen3-32b | 97.5% (2 wrong) | 97.8% | 12/12 | 2 | 0.56 s | 0.79 s | 301 / 18.8 | $0.071 |
| claude-haiku-4-5 | 91.4% (7 wrong) | 92.5% | 12/12 | 0 | 0.80 s | 0.92 s | 313 / 26.5 | $0.514 |
| claude-sonnet-5 | 96.3% (3 wrong) | 96.8% | 12/12 | 0 | 1.50 s | 1.94 s | 428 / 37.5 | $1.422 |
| claude-opus-5-5 | 96.3% (3 wrong) | 96.8% | 12/12 | 0 | 1.98 s | 3.85 s | 430 / 39.0 | $2.886 |
| claude-opus-5 | 92.6% (6 wrong) | 93.5% | 12/12 | 0 | 1.53 s | 2.37 s | 428 / 39.8 | $3.620 |

In-scope accuracy covers the messages Template Scout is meant to handle. Off-topic caught is how many of the off-topic messages were labeled out_of_scope. Wrongly refused is how many in-scope messages a model called out_of_scope, which is the costly direction.

## Mistakes by model

### jev-latest (4 wrong)

- "what database does Directus need?": expected repo, got out_of_scope, confidence 0.38
- "which categories are we missing templates for?": expected analysis, got search, confidence 0.36
- "what would it take to turn n8n into a template?": expected analysis, got out_of_scope, confidence 0.30
- "forget it": expected chat, got other, confidence 0.29

### qwen3-32b (2 wrong)

- "sweet": expected chat, got out_of_scope
- "forget it": expected chat, got out_of_scope

### claude-haiku-4-5 (7 wrong)

- "compare the top two of those": expected analysis, got chat
- "which of these would make the best new template?": expected analysis, got chat
- "rank these candidates for me": expected analysis, got chat
- "which categories are we missing templates for?": expected analysis, got other
- "what would it take to turn n8n into a template?": expected analysis, got repo
- "pick the best of the three and say why": expected analysis, got chat
- "recommend which one to build first": expected analysis, got chat

### claude-sonnet-5 (3 wrong)

- "which categories are we missing templates for?": expected analysis, got other
- "what would it take to turn n8n into a template?": expected analysis, got repo
- "what are you able to help with?": expected chat, got other

### claude-opus-5-5 (3 wrong)

- "what would it take to turn n8n into a template?": expected analysis, got repo
- "what are you able to help with?": expected chat, got other
- "what are you exactly?": expected chat, got other

### claude-opus-5 (6 wrong)

- "best observability tools": expected search, got other
- "what programming language is Flowise built with?": expected repo, got other
- "which categories are we missing templates for?": expected analysis, got other
- "what would it take to turn n8n into a template?": expected analysis, got other
- "what are you able to help with?": expected chat, got other
- "what are you exactly?": expected chat, got other

## Where the models disagree

- "best observability tools" (expected search): jev-latest: search, qwen3-32b: search, claude-haiku-4-5: search, claude-sonnet-5: search, claude-opus-5-5: search, claude-opus-5: other
- "what programming language is Flowise built with?" (expected repo): jev-latest: repo, qwen3-32b: repo, claude-haiku-4-5: repo, claude-sonnet-5: repo, claude-opus-5-5: repo, claude-opus-5: other
- "what database does Directus need?" (expected repo): jev-latest: out_of_scope, qwen3-32b: repo, claude-haiku-4-5: repo, claude-sonnet-5: repo, claude-opus-5-5: repo, claude-opus-5: repo
- "compare the top two of those" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis
- "which of these would make the best new template?" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis
- "rank these candidates for me" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis
- "which categories are we missing templates for?" (expected analysis): jev-latest: search, qwen3-32b: analysis, claude-haiku-4-5: other, claude-sonnet-5: other, claude-opus-5-5: analysis, claude-opus-5: other
- "what would it take to turn n8n into a template?" (expected analysis): jev-latest: out_of_scope, qwen3-32b: analysis, claude-haiku-4-5: repo, claude-sonnet-5: repo, claude-opus-5-5: repo, claude-opus-5: other
- "pick the best of the three and say why" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis
- "recommend which one to build first" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis
- "sweet" (expected chat): jev-latest: chat, qwen3-32b: out_of_scope, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat
- "forget it" (expected chat): jev-latest: other, qwen3-32b: out_of_scope, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat
- "what are you able to help with?" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: other, claude-opus-5-5: other, claude-opus-5: other
- "what are you exactly?" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: other, claude-opus-5: other

## Caveats

- 93 messages written and labeled by one person; some labels are judgment calls.
- One message per call with no history, which undersells models that use conversation.
- Single run per model: Jev and the LLMs can answer differently on a rerun.
- Measures classification only, not answer quality. Cost is estimated from list prices.
