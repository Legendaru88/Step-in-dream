import re

from app.schemas.goal_plan import GoalPlan

STEP_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$")
TITLE_RE = re.compile(r"^\s*цель\s*:\s*(.+)$", re.IGNORECASE)


class GoalParserError(ValueError):
    pass


def _normalize(text: str) -> str:
    return " ".join(text.strip().split())


def parse_goal_plan(text: str) -> GoalPlan:
    if not text or not text.strip():
        raise GoalParserError("LLM response is empty")

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    title: str | None = None
    steps: list[str] = []

    for line in lines:
        title_match = TITLE_RE.match(line)
        if title_match:
            title = _normalize(title_match.group(1))
            break

    if title is None:
        first_line = lines[0]
        cleaned = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", first_line)
        title = _normalize(cleaned)

    in_steps = False
    for line in lines:
        if re.match(r"^\s*этапы\s*:\s*$", line, flags=re.IGNORECASE):
            in_steps = True
            continue

        step_match = STEP_RE.match(line)
        if in_steps and step_match:
            steps.append(_normalize(step_match.group(1)))
        elif in_steps and not step_match and steps:
            # Stop on first non-step line after steps have started.
            break

    if not steps:
        for line in lines:
            step_match = STEP_RE.match(line)
            if step_match:
                steps.append(_normalize(step_match.group(1)))

    if not steps:
        raise GoalParserError("Could not parse steps from LLM response")

    deduped: list[str] = []
    seen: set[str] = set()
    for step in steps:
        key = step.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(step)

    trimmed_steps = deduped[:7]
    if len(trimmed_steps) < 3:
        raise GoalParserError("Need at least 3 steps")

    return GoalPlan(title=title[:255], steps=trimmed_steps, raw_response=text)
