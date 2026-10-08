# Classifier comparison

date: 2026-10-07 · messages: 93 · models: 7

## Summary

| Model | In-scope accuracy | All-message accuracy | Off-topic caught | Wrongly refused | Mean latency | p95 | Tokens in / out | $ per 1,000 calls |
|---|---|---|---|---|---|---|---|---|
| jev-latest | 95.1% (4 wrong) | 95.7% | 12/12 | 2 | 0.23 s | 0.40 s | 552 / 61.3 | $0.023 |
| qwen3-32b | 97.5% (2 wrong) | 97.8% | 12/12 | 2 | 0.56 s | 0.79 s | 301 / 18.8 | $0.071 |
| claude-haiku-4-5 | 91.4% (7 wrong) | 92.5% | 12/12 | 0 | 0.80 s | 0.92 s | 313 / 26.5 | $0.514 |
| claude-sonnet-5 | 96.3% (3 wrong) | 96.8% | 12/12 | 0 | 1.50 s | 1.94 s | 428 / 37.5 | $1.422 |
| claude-opus-5-5 | 96.3% (3 wrong) | 96.8% | 12/12 | 0 | 1.98 s | 3.85 s | 430 / 39.0 | $2.886 |
| claude-opus-5 | 92.6% (6 wrong) | 93.5% | 12/12 | 0 | 1.53 s | 2.37 s | 428 / 39.8 | $3.620 |
| coded-rules | 84.0% (13 wrong) | 80.6% | 7/12 | 0 | 0.00 s | 0.00 s | 0 / 0 | $0.000 |

## Results by message

✓ passed, ✗ failed. Each cell shows the answer.

| id | message | expected | jev-latest | qwen3-32b | claude-haiku-4-5 | claude-sonnet-5 | claude-opus-5-5 | claude-opus-5 | coded-rules |
|---|---|---|---|---|---|---|---|---|---|
| `5209455b` | what are some good otel options | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `67eb0776` | any good opentelemetry collectors? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `02cbd68d` | best observability tools | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✗ other | ✓ search |
| `f49d21a0` | good observability options? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `31d9dd67` | what are some good observability tools | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `ff3f51fd` | got any self-hosted feature toggle projects? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `cd8f360a` | diary apps | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `0714460b` | API-first content management systems | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `3bc433fa` | open source alternatives to Notion | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `e476be13` | something like dayone | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `8ba408d7` | ways to monitor Kafka clusters | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `5f946a29` | tools for tracing microservices | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `f90cb40e` | what are good log aggregation projects | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `144fffd2` | self-hosted web analytics | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `aabb65b6` | search GitHub for job queue dashboards | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `3ea9eb10` | any open source CRM worth a look? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✗ other |
| `6a8f2e51` | looking for a workflow engine | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `486433f5` | anything similar to Redash? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `6ce51210` | self-hosted password managers | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `0a5ade6e` | good alternatives to Grafana | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `ee737c3c` | durable execution frameworks | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `cb05a57d` | vector database projects | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `617501ed` | what are some self-hosted wiki options | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `c114c8b4` | apps for monitoring uptime | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `f4045867` | open source scheduling tools | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `665f4762` | what's out there for error tracking? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `222a1a13` | what apps are built on Kafka? | search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search | ✓ search |
| `5a279438` | what programming language is Flowise built with? | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✗ other | ✓ repo |
| `349fa2df` | star count for prometheus/prometheus | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `f5898309` | list the top-level folders in getsentry/sentry | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `7b5b3871` | does langgenius/dify have a compose file? | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `a290777d` | what license does Kestra use | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `564e2b35` | is featbit/featbit still maintained? | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `8c707b85` | look at the Dockerfile of immich-app/immich | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `5a53ec25` | which services does plausible/analytics use | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `4008d774` | read the README of n8n-io/n8n | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `898a61e2` | when was supabase/supabase last updated | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `423003a9` | what's in the docker folder of appsmithorg/appsmith | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `3b61652e` | what database does Directus need? | repo | ✗ out_of_scope | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `61295329` | open the compose file for outline/outline | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `e36e2a7d` | how big is the SigNoz repo | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `7f1046cd` | who maintains Uptime Kuma | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `a3d85595` | what does the Ghost repo's root folder look like | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `6c7b1943` | is Metabase's compose file runtime-ready? | repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo | ✓ repo |
| `292c5a58` | compare the top two of those | analysis | ✓ analysis | ✓ analysis | ✗ chat | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `2d43bb7d` | which of these would make the best new template? | analysis | ✓ analysis | ✓ analysis | ✗ chat | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `646967e8` | weigh the trade-offs between Grafana and Kibana | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `a287c6b7` | rank these candidates for me | analysis | ✓ analysis | ✓ analysis | ✗ chat | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `1cfe39fb` | which categories are we missing templates for? | analysis | ✗ search | ✓ analysis | ✗ other | ✗ other | ✓ analysis | ✗ other | ✗ other |
| `545265e9` | should we add Dify or Flowise? | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `ca2a8426` | summarize the strengths and risks of these projects | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `0ee19809` | which is the better fit for Aiven Runtime, Plausible or Umami? | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `4a8e090f` | what would it take to turn n8n into a template? | analysis | ✗ out_of_scope | ✓ analysis | ✗ repo | ✗ repo | ✗ repo | ✗ other | ✓ analysis |
| `2173e863` | pick the best of the three and say why | analysis | ✓ analysis | ✓ analysis | ✗ chat | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `67cf5956` | recommend which one to build first | analysis | ✓ analysis | ✓ analysis | ✗ chat | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `49d8c592` | is SigNoz or Uptrace the stronger candidate? | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `485837a3` | compare Metabase and Redash as templates | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis |
| `d5216702` | where do the existing templates overlap? | analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✓ analysis | ✗ other |
| `ce06092f` | hello! | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `e9058ab1` | yo | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `7654bd3b` | morning! | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `844347e5` | thank you | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `341f722a` | appreciate the help | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `6f2096e7` | alright, understood | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `c34045c1` | cool | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `b9043c16` | sweet | chat | ✓ chat | ✗ out_of_scope | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `eaea2385` | exactly what I needed | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `d24d7435` | forget it | chat | ✗ other | ✗ out_of_scope | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `4507f7dc` | ha, funny | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `385934c9` | oh, that's interesting | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `89cdc057` | that makes sense | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ search |
| `47843e8d` | excellent, many thanks | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `55b5e556` | my bad, I read that wrong | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `69d91e77` | nice work | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `1e592d7f` | can you explain that more simply? | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `691a8ef8` | what made you choose that one? | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `b5013eb1` | go on | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `b28cf7ed` | is that definitely right? | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ other |
| `992dc95d` | say that again? | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat |
| `8e494a73` | what are you able to help with? | chat | ✓ chat | ✓ chat | ✓ chat | ✗ other | ✗ other | ✗ other | ✓ chat |
| `0e26c6be` | what are you exactly? | chat | ✓ chat | ✓ chat | ✓ chat | ✓ chat | ✗ other | ✗ other | ✓ chat |
| `05426928` | what's the weather in Atlanta? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |
| `f0d2a809` | write me a haiku about databases | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |
| `d45b0db2` | how do I write a Dockerfile for a Python app? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✗ repo |
| `c990cc06` | what is the capital of France? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |
| `87fab88e` | explain how HNSW indexes work | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✗ search |
| `51f8270d` | translate 'good morning' into French | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |
| `d21703e8` | what's 15% of 240? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✗ other |
| `8f3dbc19` | what's the difference between TCP and UDP? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✗ other |
| `db6acc5a` | give me a regex that matches an email address | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✗ other |
| `2055ba32` | how do I undo my last git commit? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |
| `9a5c72bd` | tell me a joke about Kubernetes | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |
| `dae67444` | what year did the first iPhone come out? | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope | ✓ out_of_scope |

Test ids are `classifier-compare::<subject>::<id>`.

## Mistakes by subject

### jev-latest (4 failed)

- `classifier-compare::jev-latest::3b61652e` "what database does Directus need?": expected repo, got out_of_scope, confidence 0.38
- `classifier-compare::jev-latest::1cfe39fb` "which categories are we missing templates for?": expected analysis, got search, confidence 0.36
- `classifier-compare::jev-latest::4a8e090f` "what would it take to turn n8n into a template?": expected analysis, got out_of_scope, confidence 0.30
- `classifier-compare::jev-latest::d24d7435` "forget it": expected chat, got other, confidence 0.29

### qwen3-32b (2 failed)

- `classifier-compare::qwen3-32b::b9043c16` "sweet": expected chat, got out_of_scope
- `classifier-compare::qwen3-32b::d24d7435` "forget it": expected chat, got out_of_scope

### claude-haiku-4-5 (7 failed)

- `classifier-compare::claude-haiku-4-5::292c5a58` "compare the top two of those": expected analysis, got chat
- `classifier-compare::claude-haiku-4-5::2d43bb7d` "which of these would make the best new template?": expected analysis, got chat
- `classifier-compare::claude-haiku-4-5::a287c6b7` "rank these candidates for me": expected analysis, got chat
- `classifier-compare::claude-haiku-4-5::1cfe39fb` "which categories are we missing templates for?": expected analysis, got other
- `classifier-compare::claude-haiku-4-5::4a8e090f` "what would it take to turn n8n into a template?": expected analysis, got repo
- `classifier-compare::claude-haiku-4-5::2173e863` "pick the best of the three and say why": expected analysis, got chat
- `classifier-compare::claude-haiku-4-5::67cf5956` "recommend which one to build first": expected analysis, got chat

### claude-sonnet-5 (3 failed)

- `classifier-compare::claude-sonnet-5::1cfe39fb` "which categories are we missing templates for?": expected analysis, got other
- `classifier-compare::claude-sonnet-5::4a8e090f` "what would it take to turn n8n into a template?": expected analysis, got repo
- `classifier-compare::claude-sonnet-5::8e494a73` "what are you able to help with?": expected chat, got other

### claude-opus-5-5 (3 failed)

- `classifier-compare::claude-opus-5-5::4a8e090f` "what would it take to turn n8n into a template?": expected analysis, got repo
- `classifier-compare::claude-opus-5-5::8e494a73` "what are you able to help with?": expected chat, got other
- `classifier-compare::claude-opus-5-5::0e26c6be` "what are you exactly?": expected chat, got other

### claude-opus-5 (6 failed)

- `classifier-compare::claude-opus-5::02cbd68d` "best observability tools": expected search, got other
- `classifier-compare::claude-opus-5::5a279438` "what programming language is Flowise built with?": expected repo, got other
- `classifier-compare::claude-opus-5::1cfe39fb` "which categories are we missing templates for?": expected analysis, got other
- `classifier-compare::claude-opus-5::4a8e090f` "what would it take to turn n8n into a template?": expected analysis, got other
- `classifier-compare::claude-opus-5::8e494a73` "what are you able to help with?": expected chat, got other
- `classifier-compare::claude-opus-5::0e26c6be` "what are you exactly?": expected chat, got other

### coded-rules (18 failed)

- `classifier-compare::coded-rules::3ea9eb10` "any open source CRM worth a look?": expected search, got other
- `classifier-compare::coded-rules::1cfe39fb` "which categories are we missing templates for?": expected analysis, got other
- `classifier-compare::coded-rules::d5216702` "where do the existing templates overlap?": expected analysis, got other
- `classifier-compare::coded-rules::e9058ab1` "yo": expected chat, got search
- `classifier-compare::coded-rules::7654bd3b` "morning!": expected chat, got search
- `classifier-compare::coded-rules::341f722a` "appreciate the help": expected chat, got search
- `classifier-compare::coded-rules::6f2096e7` "alright, understood": expected chat, got search
- `classifier-compare::coded-rules::b9043c16` "sweet": expected chat, got search
- `classifier-compare::coded-rules::eaea2385` "exactly what I needed": expected chat, got search
- `classifier-compare::coded-rules::d24d7435` "forget it": expected chat, got search
- `classifier-compare::coded-rules::4507f7dc` "ha, funny": expected chat, got search
- `classifier-compare::coded-rules::89cdc057` "that makes sense": expected chat, got search
- `classifier-compare::coded-rules::b28cf7ed` "is that definitely right?": expected chat, got other
- `classifier-compare::coded-rules::d45b0db2` "how do I write a Dockerfile for a Python app?": expected out_of_scope, got repo
- `classifier-compare::coded-rules::87fab88e` "explain how HNSW indexes work": expected out_of_scope, got search
- `classifier-compare::coded-rules::d21703e8` "what's 15% of 240?": expected out_of_scope, got other
- `classifier-compare::coded-rules::8f3dbc19` "what's the difference between TCP and UDP?": expected out_of_scope, got other
- `classifier-compare::coded-rules::db6acc5a` "give me a regex that matches an email address": expected out_of_scope, got other

## Where subjects disagree

- `02cbd68d` "best observability tools" (expected search): jev-latest: search, qwen3-32b: search, claude-haiku-4-5: search, claude-sonnet-5: search, claude-opus-5-5: search, claude-opus-5: other, coded-rules: search
- `3ea9eb10` "any open source CRM worth a look?" (expected search): jev-latest: search, qwen3-32b: search, claude-haiku-4-5: search, claude-sonnet-5: search, claude-opus-5-5: search, claude-opus-5: search, coded-rules: other
- `5a279438` "what programming language is Flowise built with?" (expected repo): jev-latest: repo, qwen3-32b: repo, claude-haiku-4-5: repo, claude-sonnet-5: repo, claude-opus-5-5: repo, claude-opus-5: other, coded-rules: repo
- `3b61652e` "what database does Directus need?" (expected repo): jev-latest: out_of_scope, qwen3-32b: repo, claude-haiku-4-5: repo, claude-sonnet-5: repo, claude-opus-5-5: repo, claude-opus-5: repo, coded-rules: repo
- `292c5a58` "compare the top two of those" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis, coded-rules: analysis
- `2d43bb7d` "which of these would make the best new template?" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis, coded-rules: analysis
- `a287c6b7` "rank these candidates for me" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis, coded-rules: analysis
- `1cfe39fb` "which categories are we missing templates for?" (expected analysis): jev-latest: search, qwen3-32b: analysis, claude-haiku-4-5: other, claude-sonnet-5: other, claude-opus-5-5: analysis, claude-opus-5: other, coded-rules: other
- `4a8e090f` "what would it take to turn n8n into a template?" (expected analysis): jev-latest: out_of_scope, qwen3-32b: analysis, claude-haiku-4-5: repo, claude-sonnet-5: repo, claude-opus-5-5: repo, claude-opus-5: other, coded-rules: analysis
- `2173e863` "pick the best of the three and say why" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis, coded-rules: analysis
- `67cf5956` "recommend which one to build first" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: chat, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis, coded-rules: analysis
- `d5216702` "where do the existing templates overlap?" (expected analysis): jev-latest: analysis, qwen3-32b: analysis, claude-haiku-4-5: analysis, claude-sonnet-5: analysis, claude-opus-5-5: analysis, claude-opus-5: analysis, coded-rules: other
- `e9058ab1` "yo" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `7654bd3b` "morning!" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `341f722a` "appreciate the help" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `6f2096e7` "alright, understood" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `b9043c16` "sweet" (expected chat): jev-latest: chat, qwen3-32b: out_of_scope, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `eaea2385` "exactly what I needed" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `d24d7435` "forget it" (expected chat): jev-latest: other, qwen3-32b: out_of_scope, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `4507f7dc` "ha, funny" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `89cdc057` "that makes sense" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: search
- `b28cf7ed` "is that definitely right?" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: chat, claude-opus-5: chat, coded-rules: other
- `8e494a73` "what are you able to help with?" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: other, claude-opus-5-5: other, claude-opus-5: other, coded-rules: chat
- `0e26c6be` "what are you exactly?" (expected chat): jev-latest: chat, qwen3-32b: chat, claude-haiku-4-5: chat, claude-sonnet-5: chat, claude-opus-5-5: other, claude-opus-5: other, coded-rules: chat
- `d45b0db2` "how do I write a Dockerfile for a Python app?" (expected out_of_scope): jev-latest: out_of_scope, qwen3-32b: out_of_scope, claude-haiku-4-5: out_of_scope, claude-sonnet-5: out_of_scope, claude-opus-5-5: out_of_scope, claude-opus-5: out_of_scope, coded-rules: repo
- `87fab88e` "explain how HNSW indexes work" (expected out_of_scope): jev-latest: out_of_scope, qwen3-32b: out_of_scope, claude-haiku-4-5: out_of_scope, claude-sonnet-5: out_of_scope, claude-opus-5-5: out_of_scope, claude-opus-5: out_of_scope, coded-rules: search
- `d21703e8` "what's 15% of 240?" (expected out_of_scope): jev-latest: out_of_scope, qwen3-32b: out_of_scope, claude-haiku-4-5: out_of_scope, claude-sonnet-5: out_of_scope, claude-opus-5-5: out_of_scope, claude-opus-5: out_of_scope, coded-rules: other
- `8f3dbc19` "what's the difference between TCP and UDP?" (expected out_of_scope): jev-latest: out_of_scope, qwen3-32b: out_of_scope, claude-haiku-4-5: out_of_scope, claude-sonnet-5: out_of_scope, claude-opus-5-5: out_of_scope, claude-opus-5: out_of_scope, coded-rules: other
- `db6acc5a` "give me a regex that matches an email address" (expected out_of_scope): jev-latest: out_of_scope, qwen3-32b: out_of_scope, claude-haiku-4-5: out_of_scope, claude-sonnet-5: out_of_scope, claude-opus-5-5: out_of_scope, claude-opus-5: out_of_scope, coded-rules: other

## Notes

- In-scope accuracy covers the messages Template Scout is meant to handle. Wrongly refused counts in-scope messages a model called out_of_scope, the costly direction.
- One message per call, no conversation history; one run per model, so answers can differ on a rerun. Prices are the list prices in settings.toml.
- 93 messages written and labeled by one person; some labels are judgment calls.
