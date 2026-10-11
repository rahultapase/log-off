"""Check Gemma's answer against the facts. Every rejection carries a reason Gemma can read."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from .models import Candidate, GemmaPick, Prefs, TimeWindow

PLACE_WORDS = (
    "Park", "Garden", "Gardens", "Lake", "Temple", "Hill", "Hills", "Road", "Market", "Mall",
    "Station", "Beach", "Fort", "Ground", "Maidan", "Chowk", "Nagar", "Sector", "Tree",
)
# Capitalised words that start sentences or steps and are not names.
NOT_NAMES = {
    "the", "a", "an", "this", "that", "your", "our", "visit", "walk", "head", "go", "find", "sit",
    "at", "in", "to", "then", "enjoy", "take", "stroll", "explore", "look", "listen", "count",
    "notice", "spend", "pick", "choose", "stand", "stop", "leave", "return", "come", "back",
    "near", "inside", "around", "through", "by", "from", "on", "into", "once", "when", "while",
    "after", "before", "slowly", "quietly", "gently", "for", "and", "or", "with", "of", "its",
    "it", "is", "are", "there", "here", "share", "bring",
}
# Adjectives like "Central", "Green" or "Old" are deliberately NOT here: they start real names.
_NAME_PHRASE = re.compile(
    r"\b((?:[A-Z][\w'\u2019.-]*\s+){1,4})(" + "|".join(PLACE_WORDS) + r")\b"
)
# "Sector 21", "Sector-20", "Road No. 4": numbered localities common in Indian addresses.
_NUMBERED = re.compile(r"\b(Sector|Road|Lane|Street|Plot|Phase|Block)\s*(?:-|No\.?)?\s*(\d+[A-Z]?)\b", re.I)
_DISTANCE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:km|kms|kilomet(?:re|er)s?|met(?:re|er)s?)\b", re.I)
_CLOCK = re.compile(r"\b\d{1,2}(?::|\.)\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?|\b\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.)", re.I)
_BRACES = re.compile(r"\{(?!place\})[^}]*\}")

ALWAYS_UNSAFE = ("swim", "dive", "wade into", "jump into")
DARK_UNSAFE = ("climb", "hike", "trail", "alone", "split up", "wander off", "lie down", "nap")
RAIN_UNSAFE = ("picnic", "lie on", "lie down", "sunbathe", "sit on the grass", "nap", "stargaz")


@dataclass
class Verdict:
    ok: bool
    reason: str | None = None
    rule: int | None = None
    pick: GemmaPick | None = None
    invented: list[str] | None = None


def _text(pick: GemmaPick) -> str:
    return "\n".join([pick.title, *pick.steps, pick.why])


def invented_names(text: str, allowed_labels: list[str]) -> list[str]:
    """Proper-name + place-word phrases that aren't one of the listed places."""
    allowed = [a.lower() for a in allowed_labels]
    bad: list[str] = []
    for m in _NAME_PHRASE.finditer(text):
        words = m.group(1).split()
        while words and words[0].lower().strip(".,") in NOT_NAMES:
            words.pop(0)
        if not words:
            continue  # "The Park", "Walk to the Garden": generic
        phrase = f"{' '.join(words)} {m.group(2)}"
        low = phrase.lower()
        if any(low in a or a in low for a in allowed):
            continue
        bad.append(phrase)
    squashed = [re.sub(r"[\s-]+", "", a) for a in allowed]
    for m in _NUMBERED.finditer(text):
        key = (m.group(1) + m.group(2)).lower()
        if not any(key in s for s in squashed):
            bad.append(m.group(0))
    return bad


def check(
    raw: str | dict,
    candidates: list[Candidate],
    prefs: Prefs,
    window: TimeWindow | None,
) -> Verdict:
    # 1. JSON / schema
    try:
        pick = GemmaPick.model_validate_json(raw) if isinstance(raw, str) else GemmaPick.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ())) or "body"
        return Verdict(False, f"Invalid JSON or schema at {where}: {first.get('msg')}.", 1)

    # 2. place_id from the list
    by_id = {c.id: c for c in candidates}
    chosen = by_id.get(pick.place_id.strip())
    if chosen is None:
        return Verdict(False, f"place_id {pick.place_id!r} is not in the list. Use one of: {', '.join(by_id)}.", 2, pick)

    text = _text(pick)

    # 3. invented places
    bad = invented_names(text, [c.place.label for c in candidates])
    if bad:
        return Verdict(
            False,
            f"You named places that are not on the list: {', '.join(bad)}. Refer to the place only as {{place}}.",
            3, pick, bad,
        )

    # 4. distances and clock times are the code's job
    if _DISTANCE.search(text) or _CLOCK.search(text):
        hit = (_DISTANCE.search(text) or _CLOCK.search(text)).group(0)  # type: ignore[union-attr]
        return Verdict(False, f"Don't state distances or clock times (found {hit!r}); the app adds those.", 4, pick)
    if _BRACES.search(text):
        return Verdict(False, "Only the {place} placeholder is allowed in braces.", 4, pick)

    # 5. time budget
    total = 2 * chosen.walk_min + pick.duration_min
    if total > prefs.minutes:
        allowed = prefs.minutes - 2 * chosen.walk_min
        return Verdict(
            False,
            f"duration_min {pick.duration_min} is too long: the walk there and back is {2 * chosen.walk_min} min "
            f"of {prefs.minutes}. Use at most {allowed}.",
            5, pick,
        )

    # 6. safety for the conditions
    low = text.lower()
    unsafe = [w for w in ALWAYS_UNSAFE if w in low]
    if window is not None and window.mode == "after_dark":
        unsafe += [w for w in DARK_UNSAFE if w in low]
    if window is not None and window.rain_risk:
        unsafe += [w for w in RAIN_UNSAFE if w in low]
    if unsafe:
        return Verdict(False, f"Not safe for the conditions: {', '.join(unsafe)}. Suggest something else.", 6, pick)

    return Verdict(True, pick=pick)


def render(pick: GemmaPick, label: str) -> GemmaPick:
    """Put the real place label where Gemma wrote {place}."""
    sub = lambda s: s.replace("{place}", label)  # noqa: E731
    return pick.model_copy(update={"title": sub(pick.title), "steps": [sub(s) for s in pick.steps], "why": sub(pick.why)})
