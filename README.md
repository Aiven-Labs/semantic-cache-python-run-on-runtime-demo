# Template Scout

Search popular GitHub projects and see how they compare to the apps already on
[templates.aiven.io](https://templates.aiven.io), to find new Aiven Runtime template candidates.

## How it works

1. **Search.** Type what you're looking for. The app searches GitHub for the most-starred
   matching repos (30 per search, more than 100 stars) and checks each for a Compose file the
   way Aiven Runtime reads it (`build:` = app, postgres/kafka/valkey/redis/opensearch images =
   data services; image-only apps and repos without Compose are flagged).
2. **Index.** Each repo is embedded and stored in a Valkey vector index next to the 25 existing
   templates. Its distance to the nearest template is the **novelty** score.
3. **Rank.** Results come from `FT.SEARCH` KNN over everything indexed, so earlier searches
   enrich later ones. Sort by match, stars, or novelty.
4. **Semantic cache.** A search within cosine distance 0.10 of an earlier one skips GitHub
   ("headless CMS" vs "headless cms self hosted") and answers from the index.

See [docs/flow.md](docs/flow.md) for diagrams of the whole app: the system, search and the
semantic cache, how a chat message picks its model, one chat turn, the repo panel, and what lives
in Valkey.

## Terminal UI

```sh
mise run up      # the web app must be running (the TUI is a client of it)
mise run tui     # or: SCOUT_URL=https://... SCOUT_GH_USER=you mise run tui
```

Three tabs, switched with **F1 / F2 / F3**:

| Tab | What it does |
|---|---|
| Search | type a topic, Enter: the same cached GitHub search as the web page; results ranked with match and novelty |
| Repos | every cached repo A to Z; type to filter by name, language or service |
| Chat | the same chat (routing, tools, cost), streamed; `/1`-`/4` send a suggestion, `/new`, `/debug`, `/help` |

Move with the arrow keys and press **Enter** on a repo to open its details on the right (the same
panel as the web page). Details load on Enter only, never as the cursor moves, because a repo's
first open can call GitHub once. Keys on an open repo: **m** copy the manifest entry (to your fork
if `SCOUT_GH_USER` is set) · **f** fork · **g** GitHub · **e** edit manifest.json · **r** retry
loading from GitHub · **s** cycle the search sort · **/** jump to the filter or search box · **q**
quit. Copying uses `pbcopy` (or `wl-copy` / `xclip`) and falls back to the terminal's OSC 52.

The TUI calls the web app's JSON API (`/api/search`, `/api/repos`, `/api/repo/<owner>/<name>`,
`/manifest-entry`, `/chat/send`, `/chat/debug/<id>`), so it needs no keys or model access of its
own and works against a deployed copy. Textual is an optional extra (`--extra tui`), so the web
image doesn't include it.

## Repo list and details panel

**Repos** (`/repos`) lists every repo in the index A to Z, grouped by letter, with stars, language,
Aiven services, Compose status and whether its basic info and root folder are cached. It reads
Valkey only and grows as you search. Filter by name, language or service; click a name to open its
details.

Clicking a name on the Search or Repos page slides a panel in from the right, filled by htmx from
`GET /repo/<owner>/<name>` (the same URL is a normal page if opened directly): stored facts, the
Aiven services and Compose breakdown (which services build, which only pull an image, where the
file is), the most similar existing templates and projects, the manifest entry with copy/fork/edit
links, and the cached repo info, root folder and Compose file.

**What is cached, and when**

| Data | Cached | Cost | Kept |
|---|---|---|---|
| Stars, language, license, last push, topics, archived (the repo's basic info) | when a search finds the repo | free (it comes with the search result) | 7 days |
| Compose file and its breakdown | when a search finds the repo | free (raw file download) | 7 days |
| Root folder listing | the first time the repo is opened | 1 GitHub API call | 7 days |
| Files and folders the chat reads | when the chat reads them | raw reads are free; folder listings cost 1 call | 1 hour |

After the first open, a repo's panel is served entirely from Valkey. If GitHub fails (rate limit,
network) the failure is remembered for two minutes so reopening doesn't hammer a limited API; the
**Retry** button tries again immediately. The retention windows are `detail_ttl_seconds` and
`repo_cache_ttl_seconds` in `settings.toml`. Repos indexed before these fields existed fill in when
they are found again (search with "Bypass cache") or opened.

## Chat

`/chat` is a chat UI over the same data. Each message goes through **semantic routing**: it is
embedded and matched (`FT.SEARCH` KNN, `kind=route`) against example utterances stored in Valkey.

| Route | Does |
|---|---|
| `find` | runs the GitHub search (semantically cached), answers from the top results |
| `lookup` | answers from the template list + closest indexed projects |
| `smalltalk` | answers without any context |
| `inspect` | opens a repo's files on request ("look at the files in owner/name"); has the tools below |
| `analysis` | compare / recommend / gap analysis; has the tools below |
| `agent` | **fallback when nothing matches** (distance over 0.25); the model decides what to look up |

`analysis`, `agent`, `inspect` and `repo_facts` can call tools, up to 4 rounds. There are three,
not six, because every definition is re-sent on every round and each extra tool is another chance
to pick wrongly:

| Tool | Does |
|---|---|
| `search(query, where)` | `where="github"` searches GitHub (cached by meaning); `where="index"` searches projects already indexed (free) |
| `repo(repo, path)` | no path: language, license, stars, last push and the root folder; folder path: its listing; file path: the file (first 20 KB) |
| `templates()` | the existing templates; only offered when they are not already in the prompt |

The chat shows each tool call under the reply. These are LangChain tools (plain function calling
through LiteLLM), not MCP.

**Looking inside a project.** `repo` reads files from `raw.githubusercontent.com` first (no API
quota, no credentials sent) and only lists folders through the GitHub API (1 call, so set
`GITHUB_TOKEN` if you hit the 60/hour unauthenticated limit). Repo and path input is validated
(`owner/name`, no `..`), binary files are skipped, and file contents are marked as untrusted data
in the prompt so instructions inside a repo are ignored. Listings and files are cached in Valkey
for an hour.

**Cost of tool use.** The `agent` route starts with the template list and the best indexed
projects already in its prompt (from Valkey), so it doesn't pay model rounds to fetch them;
follow-ups skip that prefetch. Search calls report whether GitHub was queried or the semantic cache
answered.

**Follow-up suggestions.** After each reply, chips below the chat offer next steps built from the
repos that reply found or opened (look at its files, compare the top two, is it Runtime-ready,
find similar). They cost nothing, since no model call is involved, and are saved with the
conversation so a reload shows them again. A new chat starts with starter chips.

- **The model depends on hit or miss, set in `settings.toml`.** A hit gets the cheapest model; a
  miss gets the expensive one.
  - **Hit:** the router matched the message confidently (a greeting, a lookup, a search request),
    **or** the cache already covers it: a similar GitHub search is cached, the index has enough
    relevant repos, or a repo's details are cached.
  - **Miss:** live GitHub data or real reasoning is needed and neither check covered it. `analysis`
    (compare, rank, recommend) always counts as a miss, since it is reasoning, not retrieval.
  - **Unmatched messages** ("oh i see", "diary apps?") go to a **classifier** first: a call of a few
    hundred tokens that says whether the message is chit-chat, a search, a question about one repo,
    an analysis, or something else. Code then checks the cache. Matched messages skip it.
    The classifier is [Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) (TypeSafe
    AI) when `TYPESAFE_API_KEY` is set. Jev picks the kind only, so the search words come from the
    message and the repo name from the catalog. Below `[routing.jev] min_confidence`, or if Jev is
    down, the mid-tier `classifier` model answers with tools. Without the key, that model classifies.

  ```toml
  [routing.models]
  hit = "qwen3-32b"                   # cheapest
  classifier = "claude-haiku-4-5"     # mid tier: fallback when Jev is off or unsure
  miss = "claude-sonnet-5-5"          # expensive (also the "saved by routing" baseline)
  [routing.coverage]                  # when does the index "cover" a search topic?
  index_hit_distance = 0.30
  index_hit_min = 3
  ```

  Each reply shows `hit`/`miss`/`pinned`/`follow-up`, the model and the reason, and the debug report
  records it. `[routing.pin]` still forces a route to one model, and short follow-ups keep the
  previous turn's route on `followup_model` without calling the classifier.

  **All chat models live on the Aiven gateway** (`SEMCACHE_LLM_BASE_URL`, a LiteLLM router): there
  is no local proxy any more. At startup the app lists the gateway's models and warns about any
  name in `settings.toml` it does not serve; `/healthz` shows them as `missing_models`. The hit
  model was chosen by a test of the gateway's cheap models on the app's own prompts (chit-chat,
  a results table, a tool call with the right repo): `qwen3-32b` 11 of 12, `claude-haiku-4-5` 12 of
  12, `nova-lite` and `ministral-3-14b` fewer. Change one line to swap it.
- **Conversations are cached in Valkey**: one list per conversation (`conv:<id>`), 7-day idle TTL,
  restored on reload. The last 8 turns go to the model as history.
- **Answers are semantically cached** for the first message of a conversation (no history to
  depend on), so a near-duplicate question gets the stored answer instantly.
- Replies stream token by token. `<think>` blocks are stripped.

## Settings file and cost

`settings.toml` holds every tunable number, read at startup (`SEMCACHE_SETTINGS_FILE` to point
elsewhere). Every key is required, unknown keys are rejected, and ranges are checked, so a typo
fails loudly. It is mounted into the app container: edit it and restart, no rebuild.

| Section | Controls |
|---|---|
| `[cache]` | cosine distance and TTL for the GitHub-search cache and the chat-answer cache |
| `[routing]` | router cutoffs, the hit/miss models and coverage test, always-expensive routes, per-route pins, follow-up model |
| `[chat]` | history turns, conversation TTL, tool rounds |
| `[search]` | GitHub results per new search |
| `[cost.models."<name>"]` | USD per 1M input / output tokens for each model |

Prices are estimates you maintain (the gateway publishes none). Each chat reply shows its cost, and
what was saved: **by cache** (the original answer's cost) or **by routing** (the same tokens
priced at the `miss` model, minus the chosen model's cost; a counterfactual, not a bill). Totals are kept in Valkey and
served at `/stats`. Token counts come from the model server; if it sends none, they are
estimated at about 4 characters per token and flagged.

## Run locally

All of these must be in the environment (fnox). There are no defaults and the app won't start
without them:

| Variable | Example |
|---|---|
| `SEMCACHE_EMBED_BASE_URL` | `http://127.0.0.1:8001/v1` |
| `SEMCACHE_EMBED_API_KEY` | (secret) |
| `SEMCACHE_EMBED_MODEL` | `Qwen3-Embedding-0.6B-4bit-DWQ` |
| `SEMCACHE_EMBED_DIM` | `1024` |
| `SEMCACHE_LLM_BASE_URL` | the Aiven AI gateway (OpenAI-compatible LiteLLM router); serves every chat model |
| `SEMCACHE_LLM_API_KEY` | (secret) key for that gateway |
| `TYPESAFE_API_KEY` | (secret, optional) TypeSafe AI key; turns on the Jev classifier |

`GITHUB_TOKEN` is optional (raises rate limits). Embeddings are the one thing still local: the
gateway has no embeddings endpoint, so `SEMCACHE_EMBED_*` points at OMLX, and in `compose.yaml`
the base URL is `host.docker.internal` so the container can reach OMLX on the host.

```sh
mise run up      # docker compose: app + valkey-bundle (has the search module)
# open http://localhost:8000
# or: uv sync && mise run test && mise run dev
```

If you change the embedding model or dimension, drop the old indexes first:
`FT.DROPINDEX idx:catalog` and `FT.DROPINDEX idx:crawlcache`.

## Deploy on Aiven Runtime

Runtime reads a Compose file where the app has `build:` and a `valkey` data service is replaced
by Aiven for Valkey, with `VALKEY_URL` injected. Chat models are on the gateway, which Aiven can
reach. **Embeddings are the blocker**: local OMLX is not reachable from Aiven, and the gateway has
no embeddings endpoint, so an embeddings service Aiven can reach is needed first (changing the
embedding model means re-embedding every vector and re-tuning the distance thresholds in
`settings.toml`). Confirm the Valkey service has search enabled.

## Benchmarks

Both write a report into `benchmarks/`. They need the secrets in fnox, and `mise run` supplies them.

```sh
mise run bench-classifiers                              # Jev, Qwen, Haiku, Sonnet, Opus -> report.md
mise run bench-classifiers -- claude-opus-5 qwen3-32b   # or pick your own models
mise run bench-routing                                  # router strategies on the same messages
uv run pytest tests/test_benchmark.py tests/test_classifier_report.py   # no network needed
```

- `benchmarks/routing.jsonl` is the labeled set (93 messages, 12 of them off-topic). Add your own
  lines as `{"text": "...", "route": "find|inspect|analysis|smalltalk|agent"}`; `agent` means
  out of scope.
- Any model name your gateway serves works for the classifier comparison. Jev is a name starting
  with `jev` and needs `TYPESAFE_API_KEY`. Prices come from `[cost.models]` in `settings.toml`; a model
  with no entry is reported as "no price".
- The classifier comparison makes about 93 calls per model, one at a time, so Opus takes a few
  minutes. The routing benchmark needs Valkey with the search module and the embeddings server up,
  and uses its own `idx:bench` index, never the app's data.

## Next

- Semantic routing: classify a repo into a template category.
- Bloom filters: skip repos already reviewed or rejected.
- Dockerfile-only repos.
