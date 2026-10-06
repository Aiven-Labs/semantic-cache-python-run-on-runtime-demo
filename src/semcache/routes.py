"""Semantic routing: match a message to the nearest example utterance stored in Valkey.

Exemplars live in the same vector index as the catalog (kind=route). The route name is stored
in `name`, so routing is one KNN query: nearest exemplar wins.
"""

import re
from dataclasses import dataclass

from .catalog import Catalog
from .embed import Embedder


@dataclass(frozen=True)
class Route:
    exemplars: tuple[str, ...]


FALLBACK = "agent"  # no confident match: a tool-using agent decides what to look up

ROUTES: dict[str, Route] = {
    "find": Route(
        (
            "find me self-hosted feature flag apps",
            "search GitHub for headless CMS projects",
            "look for popular job queue dashboards",
            "what open source projects exist for error tracking",
            "discover new apps that use Kafka",
            "show me projects like Metabase",
            "durable functions",
            "feature flags",
            "headless CMS",
            "kafka monitoring tools",
            "background job queue",
        ),
    ),
    "lookup": Route(
        (
            "which templates already use Valkey",
            "does the catalog have a Kafka template",
            "list the existing templates",
            "what does the Keycloak template do",
            "how many templates use PostgreSQL",
            "is there already a template for analytics",
        ),
    ),
    "analysis": Route(
        (
            "compare these projects and recommend which would make the best new template",
            "why is this project a good fit for Aiven Runtime",
            "what gaps exist in the current templates",
            "should we add this app, weigh the trade-offs",
            "summarize the strengths and risks of these candidates",
            "what would it take to turn this repo into a template",
        ),
    ),
    "repo_facts": Route(
        (
            "what language is Dify written in",
            "how many stars does grafana/grafana have",
            "what license does this project use",
            "when was the repo last updated",
            "is this project still maintained",
            "which services does Kestra use",
        ),
    ),
    "inspect": Route(
        (
            "show me the files in grafana/grafana",
            "look at the Dockerfile of this repo",
            "what is in the docker compose file of owner/repo",
            "read the README of that project",
            "list the files in the repository",
            "open the compose file for featbit/featbit",
        ),
    ),
    # No exemplars: reached only when nothing above matches. Model + tool use.
    "agent": Route(()),
    # Conversation about the conversation: greetings, reactions, thanks, "explain that", "why did
    # you pick that". No new research is needed, so no tools and no context: history is enough.
    "smalltalk": Route(
        (
            "hi",
            "hey there",
            "good morning",
            "good evening",
            "how's it going?",
            "what's up",
            "thanks",
            "thanks, that helps",
            "that's really helpful, thanks",
            "got it, thanks a lot",
            "great, thank you",
            "ok",
            "ok got it",
            "okay cool",
            "got it",
            "perfect",
            "nice one",
            "awesome",
            "cool, that makes sense",
            "makes sense",
            "hmm interesting",
            "interesting",
            "lol",
            "haha",
            "you're awesome",
            "sorry, I misread that",
            "never mind",
            "ignore that",
            "what can you do",
            "how does this work",
            "who are you",
            "can you explain that a bit more?",
            "can you say that more simply?",
            "can you repeat that?",
            "what do you mean by that?",
            "why did you pick that one?",
            "tell me more",
            "what do you think?",
            "are you sure?",
            "that's wrong",
            "I'm not sure that's what I wanted",
        ),
    ),
}


def seed_routes(catalog: Catalog, embedder: Embedder) -> None:
    for name, route in ROUTES.items():
        for text in route.exemplars:
            ident = f"{name}:{text}"
            if not catalog.exists("route", ident):
                catalog.upsert(
                    "route", ident, embedder.embed(text),
                    {"name": name, "description": text, "services": []},
                )  # fmt: skip


_QUESTION_START = re.compile(
    r"^(why|how|what|which|who|when|where|should|could|would|can|is|are|do|does|compare)\b", re.I
)


_CONVERSATIONAL = re.compile(
    r"\b(thanks?|thank you|thx|ok(ay)?|cool|nice|great|awesome|perfect|lol|haha|hmm+|interesting|"
    r"sorry|never ?mind|good (morning|afternoon|evening|night)|hello|hi|hey|you'?re|that'?s|i'?m|"
    r"please|wrong|sure)\b",
    re.I,
)


def looks_like_topic(text: str) -> bool:
    """A short noun phrase to search for ('diary apps?'). Not a question, not chit-chat."""
    text = text.strip()
    return (
        0 < len(text.split()) <= 5
        and not _QUESTION_START.match(text)
        and not _CONVERSATIONAL.search(text)
    )


def match_route(
    hits: list[dict], max_distance: float, limits: dict[str, float] | None = None
) -> tuple[str | None, float]:
    """(route, distance) if the nearest example is close enough to trust, else (None, distance)."""
    distance = hits[0]["distance"] if hits else 1.0
    name = hits[0]["name"] if hits else ""
    limit = (limits or {}).get(name, max_distance)
    return (name, distance) if name in ROUTES and distance <= limit else (None, distance)


def choose(
    hits: list[dict], max_distance: float, text: str = "", limits: dict[str, float] | None = None
) -> tuple[str, float]:
    """Pick a route from KNN hits. Weak matches become a search for bare topics, else analysis."""
    name, distance = match_route(hits, max_distance, limits)
    if name:
        return name, distance
    return ("find" if looks_like_topic(text) else FALLBACK), distance


def route_message(
    catalog: Catalog,
    embedder: Embedder,
    text: str,
    max_distance: float,
    limits: dict[str, float] | None = None,
):
    hits = catalog.search(embedder.embed(text), "route", k=1)
    return choose(hits, max_distance, text, limits)


def route_match(
    catalog: Catalog,
    embedder: Embedder,
    text: str,
    max_distance: float,
    limits: dict[str, float] | None = None,
) -> tuple[str | None, float]:
    """Like route_message, but says "no match" instead of guessing a route."""
    hits = catalog.search(embedder.embed(text), "route", k=1)
    return match_route(hits, max_distance, limits)
