"""A rule-based classifier: the "coded solution" the model classifiers are compared against.

Written once, in one pass, from the app's existing regexes (`looks_like_topic`, the conversational
pattern) plus ordinary keyword rules, and not tuned against the benchmark results. I had already
seen the 93 messages when I wrote it, so on messages it has never seen it would do worse.
Same six kinds as the model classifiers; it never sees conversation history.
"""

import re

from semcache.routes import _CONVERSATIONAL, looks_like_topic

OWNER_NAME = re.compile(r"(?<![\w./-])[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}(?![\w/-])")
OFF_TOPIC = re.compile(
    r"\b(weather|joke|poem|haiku|translate|recipe|capital of|what year|how do i (undo|install))\b",
    re.I,
)
ANALYSIS = re.compile(
    r"\b(compare|rank|versus|vs\.?|trade-?offs?|better fit|stronger|best of|recommend|"
    r"strengths|risks|gaps|which (one|of)|should we|pick the best|what would it take)\b",
    re.I,
)
REPO_FACT = re.compile(
    r"\b(language|license|stars?|maintained|last updated|readme|dockerfile|compose file|"
    r"folders?|files|repo|written in|built with|who maintains|how big|database does)\b",
    re.I,
)
SEARCH = re.compile(
    r"\b(find|search|looking for|alternatives?|similar|something like|tools?|apps?|projects?|"
    r"options|frameworks|managers|systems|engines?|dashboards?|platforms?|out there)\b",
    re.I,
)
META_CHAT = re.compile(
    r"\b(explain that|repeat|say that again|tell me more|go on|are you sure|"
    r"what (can|are) you|who are you|why did you|what made you)\b",
    re.I,
)


def classify(text: str) -> str:
    t = text.strip()
    if OFF_TOPIC.search(t):
        return "out_of_scope"
    if OWNER_NAME.search(t):
        return "analysis" if ANALYSIS.search(t) else "repo"
    if ANALYSIS.search(t):
        return "analysis"
    if META_CHAT.search(t) or (len(t.split()) <= 6 and _CONVERSATIONAL.search(t)):
        return "chat"
    if REPO_FACT.search(t):
        return "repo"
    if SEARCH.search(t) or looks_like_topic(t):
        return "search"
    return "other"
