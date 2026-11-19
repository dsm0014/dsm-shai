"""Tier routing (spec 13). Pure and deterministic: the tier comes from the step tag, the local failure count and the
orchestrator mode. Model output is never an input, so a model cannot pick or change its own tier."""

TAGS = ("normal", "hard")


def route(tag, local_failures, orchestrator="haiku"):
    """Return "chat" or "haiku". `orchestrator` is the task-wide mode: "chat" means local workers only."""
    if orchestrator == "chat":
        return "chat"
    if tag == "hard" or local_failures >= 2:
        return "haiku"
    return "chat"
