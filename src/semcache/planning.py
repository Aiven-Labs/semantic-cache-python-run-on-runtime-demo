"""Plan with a free model, execute with a larger one.

A free local model reads the question and the local context and writes a short numbered plan.
The model chosen by the distance table then carries it out with the tools and a step limit. The
plan is advice, not a script: the executor may adapt it to what the tools actually return.
"""

import re

MAX_PLAN_CHARS = 1200
TOOL_NAMES = ("search", "repo", "templates")
_STEP = re.compile(r"^\s*(\d+)[.)]\s+`?(\w+)", re.M)

PLAN_PROMPT = """You are the planner for Template Scout, which helps pick new apps for \
templates.aiven.io (ready-to-deploy apps for Aiven Runtime: PostgreSQL, Valkey, Kafka, OpenSearch).
A stronger model will execute your plan with these tools:
- search("topic", "github"): search GitHub for popular projects (cached); "index" searches the
  projects already indexed locally (free)
- repo("owner/name", "path"): no path = language, license, stars and root folder; a folder path =
  its listing; a file path = the file's first 20 KB (cached)
- templates(): the existing templates

Write a numbered plan of at most {max_steps} steps for answering the user's LATEST message. Each \
step is ONE action: a tool call with its arguments, or "Answer". Rules:
- Skip any step the context below already answers; if it all fits, the plan is just "1. Answer".
- Use exact owner/name values from the context. Never invent an owner.
- To inspect a project, list its root folder first, then read exactly the files you saw.
- After the steps, add one line starting with "Answer should:" saying what to include.
Reply with the plan only: no reasoning, no preamble. Example of the exact format:
1. repo("owner/name", "")
2. repo("owner/name", "docker-compose.yml")
3. Answer
Answer should: say which Aiven services it needs and whether the app builds from source."""


def should_plan(
    route: str, inherited: bool, pricing, model: str, planner: str, max_steps: int,
    routes: set[str] | list[str],
) -> bool:  # fmt: skip
    """Plan only where it pays: a tool route, a fresh question, a planner that costs less than the
    executor (a free local model vs a paid one), and tool steps to plan for."""
    return (
        route in routes
        and not inherited
        and bool(planner)
        and max_steps > 0
        and pricing.pricier(model, planner)
    )


def clean_plan(text: str) -> str:
    """Drop reasoning tags, trim, and cap the length. Empty if nothing usable is left."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"</?think>", "", text).strip()
    if len(text) > MAX_PLAN_CHARS:
        text = text[:MAX_PLAN_CHARS].rsplit("\n", 1)[0].rstrip() + "\n..."
    return text


def parse_plan(text: str, max_steps: int) -> str:
    """Accept a plan only if it really is one; otherwise return "" (the executor runs without).

    A reasoning model often writes its thinking where the plan should be. The plan must be
    consecutive numbered steps, each an allowed tool call or "Answer", at most max_steps + 1 of
    them, optionally followed by an "Answer should:" line. Anything else is discarded, because a
    junk plan sent to a paid model makes it do extra, expensive work.
    """
    text = clean_plan(text)
    steps = _STEP.findall(text)
    if not steps or len(steps) > max_steps + 1:
        return ""
    for _, word in steps:
        if word != "Answer" and word not in TOOL_NAMES:
            return ""
    kept: list[str] = []
    for line in text.splitlines():
        if _STEP.match(line) or line.strip().startswith("Answer should:"):
            kept.append(line.strip())
        elif kept and line.strip():  # prose after the plan has started: not a clean plan
            return ""
    return "\n".join(kept)


def plan_block(plan: str, planner: str) -> str:
    """The text added to the executor's system prompt."""
    return (
        f"A free local model ({planner}) drafted this plan for the user's latest message. Follow "
        "it unless the tool results show a better path, and skip steps you no longer need. You "
        "choose the actual tool calls.\n\n" + plan
    )
