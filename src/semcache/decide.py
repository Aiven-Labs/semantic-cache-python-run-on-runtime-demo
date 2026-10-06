"""Which model answers: a hit gets the cheapest, a miss gets the expensive one.

A message is a HIT when we already have what we need: the router matched it confidently, or the
cache covers it (a similar GitHub search is cached, the index has enough relevant repos, or a
repo's details are cached). A MISS means live GitHub data or real reasoning is needed.

When the router does not match, a mid-tier model reads the message and recent turns and says what
the user wants; code then checks the cache to decide hit or miss. The mid-tier call is tiny
(a few hundred tokens in, a few dozen out), which is what makes it cheaper than guessing wrong.
"""

import json
import re
from dataclasses import dataclass

# What the classifier may answer, and the route each kind runs as.
KIND_TO_ROUTE = {
    "chat": "smalltalk",
    "search": "find",
    "repo": "inspect",
    "analysis": "analysis",
    "other": "agent",
}

CLASSIFY_PROMPT = """You classify the user's latest message for Template Scout, an assistant that \
finds open-source apps worth adding to templates.aiven.io.
Reply with ONLY one JSON object, no other text: {"kind": "...", "query": "...", "repo": "..."}

kind is exactly one of:
- "chat": a greeting, thanks, reaction, or a question about the conversation itself ("explain \
that", "why did you pick it", "tell me more"). Nothing new needs to be looked up.
- "search": the user wants projects on a topic ("diary apps", "something like dayone"). Put 2-5 \
search words in "query".
- "repo": a question about one specific GitHub project. Put its owner/name in "repo" if it is \
given or clear from the conversation, otherwise "".
- "analysis": compare, rank, recommend, or weigh trade-offs among projects or templates.
- "other": anything else.
Leave "query" and "repo" as "" when they do not apply."""

_JSON = re.compile(r"\{.*\}", re.S)
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


@dataclass
class Decision:
    route: str
    model: str
    tier: str  # "hit" | "miss" | "follow-up" | "pinned"
    reason: str
    distance: float
    query: str = ""  # search words chosen by the classifier, when it ran
    classifier_used: bool = False
    repo: str = ""  # owner/name the classifier resolved, so the model is told it, not left to guess

    @property
    def is_hit(self) -> bool:
        return self.tier == "hit"


def parse_classification(text: str) -> dict:
    """Pull the JSON object out of the reply; anything unusable becomes kind 'other'."""
    out = {"kind": "other", "query": "", "repo": ""}
    m = _JSON.search(re.sub(r"<think>.*?</think>", "", text or "", flags=re.S))
    if not m:
        return out
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return out
    if not isinstance(data, dict):
        return out
    kind = str(data.get("kind", "")).strip().lower()
    out["kind"] = kind if kind in KIND_TO_ROUTE else "other"
    out["query"] = " ".join(str(data.get("query") or "").split())[:80]
    repo = str(data.get("repo") or "").strip()
    out["repo"] = repo if _REPO.match(repo) and set(repo.split("/")[0]) != {"."} else ""
    return out


def index_covers(distances: list[float], max_distance: float, min_count: int) -> bool:
    """Enough indexed repos sit close to the topic that a fresh GitHub search would add little."""
    return sum(1 for d in distances if d <= max_distance) >= min_count


def choose_model(
    hit: bool, route: str, models, pins: dict[str, str], always_expensive: list[str] | set[str]
) -> tuple[str, str]:
    """(model, tier). A pin wins; routes that need reasoning never get the cheap model."""
    if route in pins:
        return pins[route], "pinned"
    if route in always_expensive or not hit:
        return models.miss, "miss"
    return models.hit, "hit"


def hit_or_miss(
    route: str, *, matched: bool, covered: bool, always_expensive: list[str] | set[str]
) -> tuple[bool, str]:
    """Hit or miss, with the reason in words (shown in the chat and the debug report)."""
    if route in always_expensive:
        return False, f"{route} needs reasoning, not retrieval"
    if matched:
        return True, f"router matched {route}"
    if route == "smalltalk":
        return True, "classifier: conversation, nothing to fetch"
    if route == "find":
        if covered:
            return True, "classifier: search, and the cache already covers the topic"
        return False, "classifier: search, and GitHub must be queried"
    if route == "inspect":
        if covered:
            return True, "classifier: repo question, and its details are cached"
        return False, "classifier: repo question, and its files are not cached"
    return False, "classifier: open-ended, needs tools or reasoning"
