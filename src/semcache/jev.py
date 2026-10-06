"""Jev (TypeSafe AI) as the classifier: what is an unmatched message asking for?

Jev answers with one of the options we give it, plus a confidence. It cannot return free text,
so it fills in `kind` only. The search words fall back to `extract_query` in chat.py, and the
repo name is resolved by the caller from the catalog (see `ChatService._resolve_repo`).
"""

from typesafe_sdk import Choice, TypeSafeClient

from .decide import KIND_TO_ROUTE

CRITERIA = {
    "chat": "A greeting, thanks, reaction, or a question about the conversation itself "
    "('explain that', 'why did you pick it', 'tell me more'). Nothing new needs to be looked up.",
    "search": "The user wants projects on a topic ('diary apps', 'something like dayone').",
    "repo": "A question about one specific GitHub project.",
    "analysis": "Compare, rank, recommend, or weigh trade-offs among projects or templates.",
    "other": "Anything else.",
}
assert set(CRITERIA) == set(KIND_TO_ROUTE)

INSTRUCTIONS = (
    "Template Scout finds open-source apps worth adding to templates.aiven.io. "
    "What is the user's latest message asking for?"
)


class LowConfidence(Exception):
    """Jev was not sure enough to route on its answer."""


class JevClassifier:
    def __init__(self, *, model: str, min_confidence: float, client: TypeSafeClient | None = None):
        self.model, self.min_confidence = model, min_confidence
        self.client = client or TypeSafeClient()  # reads TYPESAFE_API_KEY

    def classify(self, history: list[dict], message: str, usage: dict) -> dict:
        """{"kind", "query", "repo"} like `parse_classification`; query and repo stay empty.

        Adds the call's tokens to `usage`. Raises on API errors and on `LowConfidence`; the
        caller treats both as "classifier unavailable".
        """
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
