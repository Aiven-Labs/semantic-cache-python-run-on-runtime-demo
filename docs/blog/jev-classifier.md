---
title: "Swapping a prompt for Jev: a classifier in a semantic-cache app"
description: "How I added TypeSafe AI's Jev as the message classifier in a Valkey-backed chat app, what it can't do, the glue code that covers that, and how it compares to a general model on 93 labeled messages."
draft: true
---

Template Scout is a chat app I built on Valkey to find open source projects that could become
templates on templates.aiven.io. Most messages never need a big model. A router embeds the
message, looks for something similar it has seen, and picks a route: search GitHub, look inside a
repo, compare projects, small talk, or hand it to an agent. The route decides which model answers,
so it decides what the turn costs.

When the router has no match, something has to read the message and decide. That is the
classifier. It started as a prompt to Claude Haiku. This post is about replacing that prompt with
Jev, a decision model from TypeSafe AI, what the code looks like both ways, and how they compare.

## The job

The classifier answers one question: what is this message asking for? There are five answers, and
each maps to a route:

```python
KIND_TO_ROUTE = {
    "chat": "smalltalk",
    "search": "find",
    "repo": "inspect",
    "analysis": "analysis",
    "other": "agent",
}
```

Code takes it from there. A `search` goes to a cache-coverage check, a `repo` needs the repo name,
and `analysis` always gets the expensive model. So the classifier needs to return a kind, and for
two of the kinds, a little more: the search words and the repo name.

## Option A: a general model and a prompt

This is what the app did first. One prompt, one JSON reply:

```python
CLASSIFY_PROMPT = """You classify the user's latest message for Template Scout, an assistant that \
finds open-source apps worth adding to templates.aiven.io.
Reply with ONLY one JSON object, no other text: {"kind": "...", "query": "...", "repo": "..."}

kind is exactly one of:
- "chat": a greeting, thanks, reaction, or a question about the conversation itself ...
- "search": the user wants projects on a topic ("diary apps", "something like dayone"). Put 2-5 \
search words in "query".
- "repo": a question about one specific GitHub project. Put its owner/name in "repo" if it is \
given or clear from the conversation, otherwise "".
- "analysis": compare, rank, recommend, or weigh trade-offs among projects or templates.
- "other": anything else.
Leave "query" and "repo" as "" when they do not apply."""
```

The call is a few lines, and the reply goes through a parser that never trusts the model:

```python
llm = self.llm_for(self.models.classifier).bind(max_tokens=120)
out = llm.invoke([("human", prompt)])
return parse_classification(out.content if isinstance(out.content, str) else "")
```

```python
def parse_classification(text: str) -> dict:
    """Pull the JSON object out of the reply; anything unusable becomes kind 'other'."""
    out = {"kind": "other", "query": "", "repo": ""}
    m = _JSON.search(re.sub(r"<think>.*?</think>", "", text or "", flags=re.S))
    ...
    kind = str(data.get("kind", "")).strip().lower()
    out["kind"] = kind if kind in KIND_TO_ROUTE else "other"
    out["query"] = " ".join(str(data.get("query") or "").split())[:80]
    repo = str(data.get("repo") or "").strip()
    out["repo"] = repo if _REPO.match(repo) and set(repo.split("/")[0]) != {"."} else ""
    return out
```

The upside is that the model can write free text. It pulls "2-5 search words" out of a sentence and
spots `langgenius/dify` in "what language is Dify written in?". The downside is the rest of that
parser: strip `<think>` blocks, find the JSON in whatever came back, validate every field, and fall
back to `other` when it is garbage. Every call is also a full generation, so you pay for output
tokens and wait for them.

## Option B: Jev

Jev does not generate text. You give it a state and a question with a fixed set of options, and it
returns one option and a confidence. It is a classifier, not a chat model. There is no JSON to
parse and nothing to hallucinate, but it can only pick from the list you give it.

The options are written as criteria:

```python
CRITERIA = {
    "chat": "A greeting, thanks, reaction, or a question about the conversation itself "
    "('explain that', 'why did you pick it', 'tell me more'). Nothing new needs to be looked up.",
    "search": "The user wants to find projects, tools or options in a topic area ('diary apps', "
    "'something like dayone', 'good otel options', 'best opentelemetry collectors'). "
    "Asking what is good or available in an area is a search, not an analysis.",
    "repo": "A question about one specific GitHub project.",
    "analysis": "Compare, rank, or weigh trade-offs between specific projects or templates that "
    "are named or already on the table ('which of those two is better', 'rank these').",
    "other": "Anything else.",
}
assert set(CRITERIA) == set(KIND_TO_ROUTE)
```

That last line is a small thing I like: the criteria can't drift from the routing table without a
failing import.

The classifier class is short:

```python
class JevClassifier:
    def __init__(self, *, model: str, min_confidence: float, client: TypeSafeClient | None = None):
        self.model, self.min_confidence = model, min_confidence
        self.client = client or TypeSafeClient()  # reads TYPESAFE_API_KEY

    def classify(self, history: list[dict], message: str, usage: dict) -> dict:
        recent = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}"
            for m in history[-4:]
        )
        state = f"Recent conversation:\n{recent or '(none)'}\n\nLatest message: {message}"
        resp = self.client.system_one(
            state=state,
            questions={"kind": Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)},
            model=self.model,
        )
        usage["in"] += resp.usage.input_tokens or 0
        usage["out"] += resp.usage.output_tokens or 0
        answer = resp.answers["kind"]
        if answer.confidence < self.min_confidence:
            raise LowConfidence(f"{answer.choice} at {answer.confidence:.2f}")
        kind = answer.choice if answer.choice in KIND_TO_ROUTE else "other"
        return {"kind": kind, "query": "", "repo": ""}
```

Two things to notice. The confidence is a real number, so there is a natural place to say "not
sure": below `min_confidence` (0.6 in `settings.toml`) it raises, and the caller treats that the
same as the classifier being down and answers with the mid-tier model and tools. And the returned
`query` and `repo` are empty, because Jev cannot write them.

## The glue Jev needs

That empty `query` and `repo` is the cost of using a classifier that only picks. Something else has
to fill them in, and the code for that is plain Python.

For the repo, look for an `owner/name` in the message, then for a repo in the catalog whose name
appears as a whole word:

```python
def _resolve_repo(self, message: str) -> str:
    for token in _OWNER_NAME.findall(message):
        if self.catalog.get("candidate", token):
            return token
    near = self.catalog.search(self.embedder.embed(message), "candidate", k=8)
    for c in near:
        short = c["name"].split("/")[-1]
        if re.search(rf"(?<![\w-]){re.escape(short)}(?![\w-])", message, re.I):
            return c["name"]
    return ""
```

It returns an empty string when it is unsure, so the answering model is told nothing instead of
something invented. For search words, the app already had a regex cleanup, `extract_query`, that
turns "find me popular open source job queue dashboards" into "job queue dashboards". It is wired in
where the classifier result comes back:

```python
def _classify(self, history, message, usage):
    if self.jev:
        out = self.jev.classify(history, message, usage)
        if out["kind"] == "repo":
            out["repo"] = self._resolve_repo(message)
        elif out["kind"] == "search":
            out["query"] = extract_query(message)
        return out
    ...  # the prompt path from option A
```

Jev is only used when `TYPESAFE_API_KEY` is set, so the prompt path stays as the fallback and the
app works without a TypeSafe account.

## Two bugs, both mine

The first one cost me a day of misreading hit rates. Before the `elif out["kind"] == "search"`
branch existed, Jev returned `query: ""`, and the hit-or-miss check calls
`_search_covered(query)`, which returns False for an empty query. Every search routed by Jev was
logged as a cache miss, however warm the cache was. The comment in `jev.py` said the words fell
back to `extract_query`, but that fallback only ran later, after the decision. The fix was those
two lines above.

The second was in the criteria. I had `analysis` as "compare, rank, recommend". "What are some good
otel options" is a recommendation request, so Jev sent it to `analysis` or picked `search` at 0.37
confidence, under the 0.6 gate. Rewording the two criteria, with that example in `search`, moved all
three of my otel phrasings to `search` at 1.00.

## How they compare

I put the same 93 labeled messages through three classifiers. They are single messages with no
conversation history, labeled by me across the five kinds. The two general models get the
production prompt through the Aiven gateway: Claude Haiku 4.5, the mid-tier fallback, and
`qwen3-32b`, the cheap model the app uses for cache hits. Jev is `jev-latest`.

| | Jev | Qwen3 32B | Haiku 4.5 |
|---|---|---|---|
| Accuracy | 95.7% | 91.4% | 88.2% |
| Mean latency | 0.30 s | 0.50 s | 0.96 s |
| p95 latency | 0.43 s | 0.71 s | 1.13 s |
| Tokens per call (in / out) | 513 / 52 | 261 / 19 | 269 / 26 |
| List price per 1,000 calls | $0.02 | $0.06 | $0.40 |

Prices are list prices from `settings.toml`; TypeSafe does not meter output tokens. Jev sends more
input tokens because the criteria go with every call, and it still comes out cheapest and fastest:
about 18 times cheaper than Haiku and 3 times faster. Qwen is the closest general model. It is 3
times the price of Jev, not 18, and it is wrong on 8 messages to Jev's 4.

The two general models fail in different ways, which is more interesting than the totals. Haiku
differs from Jev on 11 messages, and 8 are `analysis` messages like "compare the top two of
those", "rank these candidates for me" and "pick the best of the three and say why". Haiku called
all of those small talk. The benchmark sends no history, so "those" and "these" point at nothing,
and Haiku read them as being about the conversation, which is the `chat` description. Qwen and Jev
got them right. I would not read too much into this: in the real app the previous turn is in the
prompt, and that is the case Haiku would handle better.

Qwen's misses go the other way. Six of its eight are everyday questions that belong in `other`:
"translate 'good morning' into French", "what's the difference between TCP and UDP?", "how do I undo
my last git commit?", "tell me a joke about Kubernetes". It called all of them small talk. It reads
`chat` as "anything conversational" and not as "about this conversation", which is a prompt problem
I could probably fix, and one Jev did not have with the same descriptions. I did not tune the
prompt for any of the three.

Jev's own misses were 4 of 93: "which categories are we missing templates for?" (find), "what would
it take to turn n8n into a template?" (agent), "forget it" (agent), and "explain how HNSW indexes
work" (small talk). The first three came back under 0.45 confidence, so in production the 0.6 gate
would have sent them to Haiku instead of acting on them. The fourth was wrong at 0.80 and would
have gone through. That is the practical argument for a classifier that reports confidence, and
also its limit: it catches most of its own mistakes, not all of them.

## Where I would use which

- **Jev** when the answer is one of a fixed list and you can write down what each option means. It
  is faster, cheaper, and its output cannot be malformed. You pay in glue code for anything that
  needs free text.
- **A general model** when you need the classifier to also extract or write something, or when the
  right answer depends on a long conversation. You pay in parsing, latency and tokens. If you go
  this way on a budget, Qwen3 32B did better than Haiku here at a sixth of the price, as long as
  the prompt keeps "chat" narrow.
- **Both** is what the app does: Jev first, and Haiku as the fallback when Jev is unsure or down.

## An experiment that did not pan out

I also tried to make the router stop using a hardcoded distance (0.25) by matching against earlier
answered questions and letting the nearest ones vote on the route. It does learn: the share of
messages that needed the classifier fell from 74% to about 35% over a run. It also made more
confident mistakes, and its accuracy ended at 86% against 95.7% for the old router, mostly
`inspect` and `analysis` messages landing on `find`. Raising the vote share it needs brings
accuracy back to roughly the classifier's own, and the savings shrink to about one call in six.
The code and numbers are on the `feat/no-hardcoded-distance` branch in `benchmarks/`.

## What this does not show

- 93 messages I wrote and labeled, so some labels are judgment calls.
- Single messages with no history, which undersells the model path.
- Jev answers vary a little between runs. The routing benchmark used a cached set at about 94%;
  the head-to-head run above scored 95.7%.
- It measures classification, not answer quality, and prices are list prices, not my invoice.
- I looked at Laya, another classifier, and dropped it before running anything: its model card says
  base checkpoints score near chance until fine-tuned.
