"""Follow-up suggestions built from what a reply actually found. No model call, so they are free."""

import re

STARTERS = [
    "Find self-hosted feature flag apps",
    "Which templates use Valkey?",
    "What gaps exist in the current templates?",
]


_LINK = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")


def follow_the_answer(seen: list[dict], answer: str) -> list[dict]:
    """Keep the repos the answer actually talks about, in the order it mentions them.

    The raw search order can contradict the answer (it may recommend the 5th hit and dismiss the
    1st), so suggestions built from it would point the wrong way. If the answer names none of
    the repos, fall back to the search order.
    """
    mentioned = [m.rstrip(".").lower() for m in _LINK.findall(answer)]
    by_name = {r["name"].lower(): r for r in seen if r.get("name")}
    ordered: list[dict] = []
    for name in mentioned:
        if name in by_name and by_name[name] not in ordered:
            ordered.append(by_name[name])
    return ordered + [r for r in seen if r.get("inspected")] if ordered else seen


def _names(seen: list[dict], inspected: bool) -> list[str]:
    out: list[str] = []
    for r in seen:
        name = r.get("name")
        if name and bool(r.get("inspected")) == inspected and name not in out:
            out.append(name)
    return out


def build_suggestions(seen: list[dict], limit: int = 4) -> list[str]:
    """Next messages worth sending, based on repos the reply surfaced or opened."""
    repos, opened = _names(seen, False), _names(seen, True)
    out: list[str] = []
    if opened:
        n = opened[0]
        out += [
            f"Is {n} ready for Aiven Runtime? What would need to change?",
            f"What would it take to turn {n} into a template?",
        ]
    if repos:
        if not opened:
            out.append(f"Look at the files in {repos[0]}")
        if len(repos) >= 2:
            out.append(f"Compare {repos[0]} and {repos[1]} as template candidates")
        out.append("Which of these would make the best new template?")
        out.append(f"Find projects similar to {repos[0]}")
    return (out or list(STARTERS))[:limit]
