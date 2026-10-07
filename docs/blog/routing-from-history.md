---
title: "I tried to get rid of the distance threshold in my semantic router"
description: "Routing chat messages by past questions instead of hand-written examples saved classifier calls, and cost accuracy. Numbers from a 93-message benchmark."
draft: true
---

Template Scout is a chat app I built on Valkey to find open source projects that could become
templates on templates.aiven.io. Every message goes through a small router that decides what to do
with it: search GitHub, look inside a repo, compare projects, make small talk, or hand it to an
agent. That decides which model answers, so it decides what the turn costs.

The router had one weakness I kept tripping over: a hardcoded distance. Embed the message, find the
nearest hand-written example, and if it is closer than 0.25 (0.28 for small talk) you have a match.
Otherwise a classifier, Jev from TypeSafe AI, reads the message and picks.

I wanted to know what happens if the router learns from real traffic instead.

## Two bugs first

Both were in the Jev path, and both made "no hardcoded distance" look better than it should have.

1. Jev only picks a kind (search, repo, analysis, chat, other). It cannot write the search words.
   The code that checks whether the cache already covers a topic needed those words, got an empty
   string, and answered "not covered". Every Jev-routed search was a cache miss, however warm the
   cache was. Filling the query in with the existing `extract_query` fixed it.
2. My Jev criteria had `analysis` as "compare, rank, recommend". "What are some good otel options"
   is a recommendation request, so Jev either picked `analysis` or picked `search` at 0.37
   confidence, under my 0.6 cutoff. Tightening the criteria took the same three phrasings to
   `search` at 1.00.

I also changed the reported distance. When Jev decides, the distance in the turn metadata is the
router's near miss, which is above the cutoff by definition. It now reads "router missed at 0.36".

## The change

Instead of comparing a message to a fixed set of labeled examples, every answered turn is stored
in the same Valkey index: the question's embedding, the route it took, the tier, and the first 600
characters of the response. A new message is matched against earlier questions. Nothing is seeded,
so a cold start sends everything to the classifier, and the classifier's answers become the history.

That version still had the 0.25. The second version removes it. The five nearest earlier questions
vote on the route, weighted by similarity. The winner has to hold at least 60% of the vote, and the
new message has to be about as close as that route's own questions have been to each other: a
running mean and standard deviation per route, kept in Valkey, and the cutoff is the mean plus two
standard deviations. A route with fewer than five samples does not match at all.

There are still constants (k, the vote share, the spread), but none of them is a distance.

## The benchmark

93 messages I labeled by hand across five routes: find (27), inspect (17), analysis (14), small
talk (23) and agent (12). Each strategy starts with an empty history, sees the messages in a shuffled
order, and sends anything it does not match to Jev. What gets stored is Jev's answer, not the true
label, so classifier mistakes can teach the router, the same as live. Five shuffles per strategy.
Jev's answers are cached in the repo, so all three strategies see the same ones.

My first run was wrong. 30 of my 93 messages were copied word for word from the old router's
hand-written examples, which handed the baseline the answers. I rewrote those 30 as new
phrasings and reran. The numbers below are from the rerun.

| Strategy | Accuracy | Classifier called | Confident mistakes per run |
|---|---|---|---|
| Old examples, fixed 0.25 | 95.7% | 58% | 2.0 |
| Past questions, fixed 0.25 | 92.5% | 89% | 2.0 |
| Past questions, vote, no distance | 86.0% | 48% | 9.6 |

"Confident mistake" means the router matched without asking Jev and was wrong. Jev on its own is
right about 94% of the time on this set, so that is what you get if you classify everything.

## What I take from it

The vote router does learn. The share of messages that needed Jev dropped from 74% in the first
third of a run to about 35% in the last. But it spends accuracy to get there. Its mistakes are
mostly `inspect` and `analysis` messages landing on `find`, because "what services does
plausible/analytics use" and "find analytics tools" share enough vocabulary that they sit close
together in embedding space. My guess, which I did not test, is that a learned spacing per route is looser than the gap
between two neighboring routes, so it cannot tell them apart.

The vote share does most of the work. With the spread fixed at 1.0:

| Vote share needed | Accuracy | Classifier called | Confident mistakes |
|---|---|---|---|
| 60% | 88.4% | 52% | 7.0 |
| 80% | 92.0% | 68% | 3.4 |
| 100% | 94.4% | 83% | 0.8 |

Every setting trades classifier savings for accuracy, and nothing I tried beat the old router on
both. At 100% the vote router matches Jev's own accuracy and skips about one call in six.

Past questions with the fixed cutoff barely saves anything here: 93 distinct messages rarely land
within 0.25 of each other. That is a limit of the dataset, not necessarily of the idea. Real traffic
repeats itself far more, and a repeat is the case history routing is good at.

## What this does not show

- It is 93 messages that I wrote and labeled, on five routes. A few of the labels are judgment
  calls ("recommend which one to build first" is analysis to me).
- Messages are single turns. Follow-ups, which the app handles separately, are not in it.
- The history is only as good as the classifier that fills it, so Jev's roughly 94% is a ceiling.
- Cold start only. I did not measure what happens after thousands of turns.
- It measures routing, not answer quality, cost in dollars, or latency beyond the ~0.18 s per Jev call.
- I also tried Laya, a classifier from ConvAI Innovations, as a Jev replacement. I dropped it before
  running anything: its model card says base checkpoints score near chance until fine-tuned.

## Try it

The harness is in the repo. `tests/test_benchmark.py` runs it against fakes in under a second, and
`benchmarks/run_routing.py` runs it live against Valkey, an embeddings server and Jev. The routing
data, Jev's cached answers and the sweep are in `benchmarks/`.

If I keep going, I would add a margin test between the top two routes before touching the vote
share again, and I would replay real chat logs instead of a set I wrote.
