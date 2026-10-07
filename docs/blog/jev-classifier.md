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

## Why not just write rules?

The obvious alternative is code. The app already has plenty of it: a regex that spots chit-chat, a
check for "a short noun phrase that is probably a search", another that strips "find me popular
open source" down to the search words. So before swapping a prompt for a model, I wrote the rules
version of this classifier, to see how far code goes. I wrote it once, from those existing regexes
plus keyword lists, and did not tune it against the results. Here is the core of it:

```python
def classify(text: str) -> str:
    t = text.strip()
    if OFF_TOPIC.search(t):          # weather|joke|poem|haiku|translate|recipe|capital of ...
        return "out_of_scope"
    if OWNER_NAME.search(t):         # something/like-this
        return "analysis" if ANALYSIS.search(t) else "repo"
    if ANALYSIS.search(t):           # compare|rank|versus|trade-offs|recommend|which of ...
        return "analysis"
    if META_CHAT.search(t) or (len(t.split()) <= 6 and _CONVERSATIONAL.search(t)):
        return "chat"
    if REPO_FACT.search(t):          # language|license|stars|maintained|readme|folders ...
        return "repo"
    if SEARCH.search(t) or looks_like_topic(t):
        return "search"
    return "other"
```

It is instant, free and deterministic, and on 81 in-scope messages it scored **84.0%** (13 wrong).
It caught 7 of the 12 off-topic messages. That is better than I expected for forty lines. It is
also optimistic, because I had already read the 93 messages when I wrote it.

The mistakes are all the same kind of mistake:

- **Vocabulary it was never given.** Nine of the 13 misses are small talk: "yo", "morning!",
  "sweet", "ha, funny", "that makes sense", "appreciate the help". None is in the keyword list, so
  they fall to the last rule, which treats any short phrase that is not a question as a search
  topic. A model reads "sweet" as a reaction without being told.
- **Phrasing without the keyword.** "any open source CRM worth a look?" is a search, but it contains
  none of the search words. "Which categories are we missing templates for?" is an analysis with no
  analysis word in it.
- **Off-topic only where I imagined it.** The stoplist caught weather, jokes and translation
  because I thought of them. It missed "explain how HNSW indexes work", "what's the difference
  between TCP and UDP?" and "what's 15% of 240?". The list of things a user might ask that this app
  should not answer has no end.

Every one of those is fixable with another keyword, and that is the problem. Each fix is a bet
about wording, each can break a message that used to work ("sweet" is a reaction, "sweet potato
apps" is a search), and the list only grows when someone notices a miss. The rules are as good as
my imagination about how people type.

A classifier moves that work somewhere else. The fix for "good otel options" was one sentence in a
description, not a regex, and the description is something I can read back in a month. It also
generalizes: nobody told Jev or Qwen about "sweet". And it reports a confidence, which a regex does
not, so the app can say "I am not sure" and fall back to a bigger model.

It is not either/or, and the app does not treat it that way. Code does what code is exact at:
pulling `owner/name` out of a message, cleaning search words, deciding whether the cache already
covers a topic, and matching a repeat of a question it has already answered, which skips the
classifier entirely. The model handles the one part that rules do badly, which is deciding what a
loosely worded sentence means. At $0.02 per thousand calls for Jev, and only on messages the
router could not match, the cost of leaving that part to a model is close to nothing.

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

I put the same 93 labeled messages through six models and the rules from the section above, one
message per call with no conversation history. 12 of the messages are off-topic ("explain how HNSW indexes work", "write me a
haiku about databases"): Template Scout is not meant to answer those. My first run gave the
classifiers no way to say so, and I scored the off-topic messages as if `other` were the right
answer, which was wrong and penalized the models that happened to say small talk. In this run every
model gets a sixth choice, `out_of_scope`, with the same wording. The app itself has no such route
yet; this is how I would score it if it did.

Five models go through the Aiven gateway with the production prompt: Haiku 4.5, Sonnet 5, Opus 5,
Opus 5.5 and Qwen3 32B, the cheap model the app uses for cache hits. Jev is `jev-latest`.

| | In-scope accuracy (81) | Off-topic caught (12) | Mean latency | $ per 1,000 calls |
|---|---|---|---|---|
| Qwen3 32B | **97.5%** (2 wrong) | 12 | 0.56 s | $0.07 |
| Claude Sonnet 5 | 96.3% (3 wrong) | 12 | 1.50 s | $1.42 |
| Claude Opus 5.5 | 96.3% (3 wrong) | 12 | 1.98 s | $2.89 |
| Jev | 95.1% (4 wrong) | 12 | **0.23 s** | **$0.02** |
| Claude Opus 5 | 92.6% (6 wrong) | 12 | 1.53 s | $3.62 |
| Claude Haiku 4.5 | 91.4% (7 wrong) | 12 | 0.80 s | $0.51 |
| Hand-written rules | 84.0% (13 wrong) | 7 | 0.00 s | $0.00 |

Prices are the gateway's list prices from `settings.toml`, which I updated for this run. TypeSafe does
not meter output tokens. The full report, with every mistake and every disagreement, is in
`benchmarks/report.md`, and `mise run bench-classifiers` regenerates it.

A few things stand out.

**Off-topic is a solved problem for a model once there is a place to put it.** All six models caught all 12; the rules caught 7. The
interesting error runs the other way: calling a real question out of scope. Qwen did it twice
("sweet", "forget it") and Jev twice ("what database does Directus need?", "what would it take to
turn n8n into a template?"). The other four never did, and neither did the rules, which never called an in-scope message off-topic but left 5 off-topic ones unflagged.

**Bigger did not mean better.** The top four are within two messages out of 81, which is inside what
relabeling a few judgment calls would change, so I would call them tied. Opus 5, the most expensive
model here, scored below Sonnet 5 and below the newer Opus 5.5. It called six in-scope messages
`other`, including "best observability tools". Haiku was the weakest, and its mistakes are a
pattern: five of its seven are `analysis` messages like "compare the top two of those" and "rank
these candidates for me", which it read as being about the conversation and called `chat`. The
benchmark sends no history, so "those" and "these" point at nothing. In the real app the previous
turn is in the prompt, and that is the case Haiku would handle better.

**Jev's mistakes announce themselves.** All four came back at 0.38 confidence or lower, so the 0.6
gate would have sent every one of them to the fallback model instead of acting on them. None of the
general models gives you that signal.

**Cost and latency are where Jev is clearly ahead.** It is about 22 times cheaper than Haiku, 60
times cheaper than Sonnet 5 and more than 100 times cheaper than Opus 5.5, and faster than all of
them. Qwen is the real alternative: 3 times Jev's price, a little over twice its latency, and the
best accuracy here. If I could not use Jev, I would use Qwen with this prompt.

Some of the mistakes are the labels' fault. "forget it" is `chat` to me and `other` or
`out_of_scope` to three models, and Sonnet 5 and both Opus models called "what are you able to help
with?" `other`, which is a defensible reading. I did not tune the prompt for any model.

## Where I would use which

- **Jev** when the answer is one of a fixed list and you can write down what each option means. It
  is the fastest and cheapest, it reports a confidence you can gate on, and its output cannot be
  malformed. You pay in glue code for anything that needs free text. It was not more accurate than
  Qwen or the bigger Claude models here, only about as accurate.
- **A general model** when you need the classifier to also extract or write something, or when the
  right answer depends on a long conversation. You pay in parsing, latency and tokens. Paying more
  did not buy accuracy here; if you go this way, Qwen3 32B was the best of the six at a fraction of
  the Claude prices. It is slower and 3 times Jev's price, and it does not report a confidence you
  can gate on.
- **Both** is what the app does: Jev first, and Haiku as the fallback when Jev is unsure or down.

## An experiment that did not pan out

I also tried to make the router stop using a hardcoded distance (0.25) by matching against earlier
answered questions and letting the nearest ones vote on the route. It does learn: the share of
messages that needed the classifier fell from 74% to about 35% over a run (all 93 messages). It also made more
confident mistakes, and its accuracy ended at 89% against 97.5% for the old router (in-scope
messages only), mostly
`inspect` and `analysis` messages landing on `find`. Raising the vote share it needs brings
accuracy back to roughly the classifier's own, and the savings shrink to about one call in six.
The code and numbers are on the `feat/no-hardcoded-distance` branch in `benchmarks/`.

## What this does not show

- The rules baseline is one pass by someone who had seen the data. A careful rewrite would score higher than 84%, and I did not try to find out how much.
- 93 messages I wrote and labeled, 81 of them in scope, so some labels are judgment calls and
  one miss is two points of accuracy.
- Single messages with no history, which undersells the model path.
- One run per model. Jev and the LLMs can answer differently on a rerun; Jev scored 95.7% and 94.5%
  on earlier runs of a slightly different setup.
- I tested and priced `claude-sonnet-5`. The app's own answering model is configured as
  `claude-sonnet-5-5`, which I did not test.
- It measures classification, not answer quality, and prices are list prices, not my invoice.
- I looked at Laya, another classifier, and dropped it before running anything: its model card says
  base checkpoints score near chance until fine-tuned.
