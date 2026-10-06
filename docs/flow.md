# Template Scout: how the app flows

Template Scout finds open-source projects that could become templates on
[templates.aiven.io](https://templates.aiven.io). Valkey is both the vector search engine and
the cache. This page is drawn from the code; each diagram names the module it comes from.

Contents: [System](#1-the-system) · [Search](#2-search-and-the-semantic-cache) ·
[Chat decision](#3-chat-which-model-answers) · [One chat turn](#4-one-chat-turn-in-order) ·
[Repo panel](#5-the-repo-details-panel) · [Manifest entry](#6-copy-manifest-entry) ·
[Stores](#7-what-lives-in-valkey) · [Models](#8-every-model-and-when-it-runs) ·
[Known limits](#9-known-limits)

---

## 1. The system

```mermaid
flowchart LR
  subgraph Clients
    WEB["Web UI<br/>search · repos · chat"]
    TUI["Terminal UI<br/>(Textual, a client of the API)"]
  end

  subgraph APP["FastAPI app (src/semcache)"]
    PAGES["HTML pages<br/>+ htmx details drawer"]
    API["JSON API<br/>/api/search · /api/repos<br/>/api/repo/owner/name"]
    CHATEP["/chat/send<br/>(NDJSON stream)"]
    SVC["ChatService<br/>router · classifier · hit/miss<br/>tools · cost"]
  end

  VK[("Valkey<br/>vector indexes + caches")]
  EMB["Embeddings<br/>OMLX on the host (local)"]
  GW["Aiven AI gateway (LiteLLM)<br/>every chat model"]
  GH["GitHub<br/>search API · raw files · contents API"]

  WEB --> PAGES
  WEB --> CHATEP
  TUI --> API
  TUI --> CHATEP
  PAGES --> VK
  API --> VK
  PAGES --> GH
  API --> GH
  CHATEP --> SVC
  SVC --> VK
  SVC --> EMB
  SVC --> GW
  SVC --> GH
  PAGES --> EMB
  API --> EMB
```

The terminal UI holds no secrets and no model access: it calls the same API, so it also works
against a deployed copy.

---

## 2. Search and the semantic cache

`GET /` and `GET /api/search` (`app.run_search`, `github.discover`, `app._crawl`).

```mermaid
flowchart TD
  Q["Search query"] --> L{"Crawl cache:<br/>a similar search before?<br/>(cosine distance ≤ 0.10, within 24 h)"}
  L -- "hit: skip GitHub" --> RANK
  L -- miss --> GHS["GitHub search<br/>30 most-starred repos (more than 100 stars)"]
  GHS --> EACH["For each repo, 12 in parallel"]
  EACH --> RAW["Download the Compose file from raw.githubusercontent<br/>(28 paths tried: root, docker/, deploy/, ...)"]
  RAW --> AN["Analyze it<br/>build: = app, image: of postgres / kafka / valkey / redis / opensearch = data service"]
  AN --> EMBR["Embed name + description + topics + services"]
  EMBR --> NOV["KNN against the 25 existing templates<br/>distance to the nearest = novelty"]
  NOV --> UP["Upsert into the catalog (kind = candidate)"]
  UP --> CACHE["Cache basic repo info and the Compose text<br/>(7 days, no API call needed)"]
  CACHE --> MARK{"Did the crawl find any repos?"}
  MARK -- yes --> STORE["Store the 'already searched' marker (24 h)"]
  MARK -- no --> SKIP["Never cache an empty crawl"]
  STORE --> RANK
  SKIP --> RANK
  RANK["Embed the query, KNN over every indexed candidate<br/>(optional filter on Aiven services)"] --> SORT["Sort: match · stars · novelty"]
  SORT --> OUT["Results with logos, Compose status,<br/>novelty, closest template"]
```

---

## 3. Chat: which model answers

`ChatService._decide` (`chat.py`, `decide.py`, `routes.py`). **A hit gets the cheapest model, a miss
gets the expensive one.**

```mermaid
flowchart TD
  M["User message"] --> H["Load history<br/>(last 8 turns; failed turns left out)"]
  H --> R["Embed the message<br/>KNN over router examples in Valkey"]
  R --> MT{"Nearest example close enough?<br/>≤ 0.25 (small talk ≤ 0.28)"}

  MT -- "yes: matched" --> MATCHED["Route = the matched route"]
  MT -- no --> FU{"Short follow-up of the previous turn?<br/>≤ 8 words, or ≤ 20 with 'that / it / the repo'<br/>and the previous route used tools"}

  FU -- yes --> FOLLOW["Route = previous route<br/>Model = followup_model (Haiku)<br/>tier: follow-up<br/>no classifier call"]
  FU -- no --> CLS["Classifier call<br/>(Jev, about 300 tokens in; Haiku if no TYPESAFE_API_KEY)<br/>chat · search · repo · analysis · other"]

  CLS -- "call failed or confidence below min" --> FALLBACK["Route = agent<br/>Model = classifier model (Haiku)<br/>tier: miss"]
  CLS --> KIND["kind → route<br/>chat→smalltalk · search→find · repo→inspect<br/>analysis→analysis · other→agent"]

  KIND --> COV{"Does the cache cover it?"}
  COV -- "search: a similar GitHub search is cached,<br/>or ≥ 3 indexed repos within 0.30" --> HIT
  COV -- "repo: info + root folder + Compose file cached" --> HIT
  COV -- "chat: nothing to fetch" --> HIT
  COV -- "otherwise" --> MISS

  MATCHED --> AE{"Route needs reasoning?<br/>(always_expensive: analysis)"}
  AE -- yes --> MISS
  AE -- no --> HIT

  HIT["HIT"] --> PIN
  MISS["MISS"] --> PIN
  PIN{"Route pinned?<br/>(repo_facts → Haiku)"}
  PIN -- yes --> PINNED["Pinned model"]
  PIN -- no --> PICK{"hit or miss"}
  PICK -- hit --> HM["hit model: qwen3-32b"]
  PICK -- miss --> MM["miss model: claude-sonnet-5-5"]
```

The model names above are today's `settings.toml`. Every chat model is on the Aiven gateway.

---

## 4. One chat turn, in order

```mermaid
sequenceDiagram
  autonumber
  participant U as User (web or TUI)
  participant A as ChatService
  participant V as Valkey
  participant E as Embeddings (OMLX)
  participant G as Aiven gateway
  participant H as GitHub

  U->>A: POST /chat/send {conversation_id, message}
  A->>V: history (conv:id list)
  A->>E: embed(message)
  A->>V: KNN over router examples
  opt nothing matched and not a follow-up
    A->>G: classifier call (Jev; Haiku without a key)
    G-->>A: kind (Jev) or {"kind", "query", "repo"} (Haiku)
  end
  A->>V: cache checks (crawl cache, index coverage, repo cache)
  A-->>U: event meta: tier, model, reason

  opt first message, route lookup or analysis
    A->>V: answer-cache lookup (distance ≤ 0.08)
    V-->>A: cached answer (if any)
    A-->>U: replay it, cost = classifier only
  end

  A->>V: context: templates and top indexed repos
  loop model rounds (max 4 tool steps)
    A->>G: stream (chosen model, tools bound)
    G-->>A: tokens and/or tool calls
    A-->>U: event token / tool / tool_result
    opt tool call
      A->>V: repo cache (info, folders, files)
      A->>H: only if not cached (search, raw file, folder listing)
    end
  end

  A->>V: save turn (answer, route, model, tools, cost)
  A->>V: stats:cost totals
  A->>V: answer cache store (lookup and analysis only)
  A-->>U: events cost, suggestions, done
```

---

## 5. The repo details panel

`GET /repo/{owner}/{name}` (htmx drawer) and `GET /api/repo/{owner}/{name}` (`details.py`).

```mermaid
flowchart TD
  CLICK["Click a repo name<br/>(Search, Repos, or Enter in the TUI)"] --> IDX{"In the catalog?"}
  IDX -- no --> NO["'Not in the index. Search for it first.'"]
  IDX -- yes --> FAIL{"GitHub failed for it<br/>in the last 2 minutes?"}
  FAIL -- yes --> SHOWERR["Show the remembered errors<br/>(no GitHub call)"]
  FAIL -- no --> ENSURE["Fetch only what is missing, once"]
  ENSURE --> I["repo info<br/>(already cached by the search: free)"]
  ENSURE --> RT["root folder<br/>(1 GitHub API call)"]
  ENSURE --> CF["Compose file<br/>(already cached by the search)"]
  I --> KEEP
  RT --> KEEP
  CF --> KEEP
  KEEP["Cache for 7 days"] --> ERR{"Any error?"}
  ERR -- yes --> NOTE["Remember it for 2 minutes<br/>'Retry' clears it"]
  ERR -- no --> BUILD
  NOTE --> BUILD
  SHOWERR --> BUILD
  BUILD["Build the view from Valkey only:<br/>facts · Aiven fit · 3 similar templates · 5 similar projects<br/>manifest entry · what is cached"] --> OUT["Slide-in panel (web) or detail pane (TUI)"]
```

Opening the details never calls GitHub twice for the same piece of data. In the TUI details load on
Enter only, never as the cursor moves.

---

## 6. Copy manifest entry

`GET /manifest-entry?repo=owner/name[&owner=you]` (`manifest.py`). No model is involved.

```mermaid
flowchart LR
  BTN["Copy manifest entry<br/>(button, or m in the TUI)"] --> GET["Catalog record for the repo"]
  GET --> BUILD["Build the entry<br/>name · owner · repo · added = today<br/>description · topics = app name, Aiven services, GitHub tags"]
  USER["Your GitHub username<br/>(optional)"] -. "owner = your fork" .-> BUILD
  BUILD --> VAL["Validate against the directory schema<br/>(extra keys are rejected)"]
  VAL --> W["Warnings: image-only Compose, no Compose,<br/>points at upstream not a fork"]
  VAL --> FMT["Format like data/manifest.json<br/>2-space indent, topics on one line"]
  FMT --> CLIP["Clipboard"]
  CLIP --> PR["Fork → add it as the last item<br/>→ pull request (the web editor link opens the PR form)"]
```

---

## 7. What lives in Valkey

| Key prefix / index | What | Written by | Lifetime |
|---|---|---|---|
| `idx:catalog` over `catalog:*` | Existing templates, discovered repos (`candidate`), router examples (`route`); each has a 1024-d embedding | startup, every search | no expiry |
| `idx:crawlcache` over `crawlcache:*` | "This topic was searched" markers, matched by meaning | search | 24 h |
| `idx:chatcache` over `chatcache:*` | First-message answers for `lookup` and `analysis`, matched by meaning | chat | 24 h |
| `conv:<id>` | One conversation: turns, route, model, tools, cost, suggestions | chat | 7 days idle |
| `repocache:info / ls / file / fail` | Repo info, folder listings, files; remembered GitHub failures | search, panel, chat tools | 7 days (search and panel), 1 h (chat reads), 2 min (failures) |
| `stats:cost` | Running spend and savings totals | chat | no expiry |

Search can be tuned in `settings.toml`: every distance, TTL, price and model named above.

---

## 8. Every model and when it runs

| Model | Role | Runs when | Where |
|---|---|---|---|
| Qwen3-Embedding-0.6B | embeddings (1024-d) | every message (route lookup, answer-cache lookup, search coverage), every repo ingested | OMLX on the host, **not** the gateway |
| `qwen3-32b` | **hit** | the router matched, or the cache covers the message (and the route is not pinned or always-expensive) | gateway |
| `jev-latest` | **classifier** | the router matched nothing and it is not a short follow-up | TypeSafe API (`TYPESAFE_API_KEY`) |
| `claude-haiku-4-5` | classifier fallback | no TYPESAFE_API_KEY, or the agent answer when Jev fails or is unsure | gateway |
| `claude-haiku-4-5` | follow-up and pinned `repo_facts` | short follow-ups; router-matched repo-fact questions | gateway |
| `claude-sonnet-5-5` | **miss** | live GitHub data or reasoning is needed: `analysis` always, uncached searches, uncached repo questions, open-ended | gateway |
| *(none)* | answer cache | the first message repeats an earlier `lookup` or `analysis` question | Valkey |

Prices in the cost readout are estimates in `settings.toml` (the gateway publishes none), and
"saved by routing" is a counterfactual against the miss model, not a bill.

---

## 9. Known limits

- **No failover.** If the chosen model errors, the turn ends with an error; it is not retried on
  another model. Only a failed classifier falls back (to Haiku with tools).
- **Repo questions are expensive when nothing is cached.** A question like "what license does Dify
  use?" is a miss until the repo's root folder is cached, so it runs on Sonnet even though the
  license is already stored.
- **The classifier runs before the answer-cache lookup**, so a cached analysis still pays for it.
  Its cost is now counted.
- **Embeddings are the one local dependency.** The gateway has no embeddings endpoint, which blocks
  deploying on Aiven Runtime until embeddings move somewhere Aiven can reach.
- Hit and classifier quality come from small models; the chat tests cover routing and cost, not the
  wording of answers.
