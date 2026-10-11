"""Deterministic activities for when Gemma is off or keeps failing validation."""

from __future__ import annotations

from .models import Candidate, GemmaPick, Prefs

GREEN = {"park", "garden", "nature_reserve", "wood"}

TEMPLATES: dict[str, dict[str, tuple[str, list[str], str]]] = {
    "calm": {
        "green": ("Five sounds at {place}", [
            "Walk to {place} without your phone in your hand.",
            "Find a bench or a quiet edge and sit for a few minutes.",
            "Count five different sounds before you get up.",
        ], "A green place close by, good for slowing down."),
        "other": ("Sit for a while at {place}", [
            "Walk to {place} at an easy pace.",
            "Sit somewhere you can watch people come and go.",
            "Breathe out slowly ten times, then walk back.",
        ], "A calm spot within your time."),
    },
    "curious": {
        "green": ("Look closer at {place}", [
            "Walk to {place} and do one slow lap.",
            "Find three plants or trees you can't name and look at their leaves.",
            "Pick the one you'd like to know more about and remember it.",
        ], "Somewhere with something new to notice."),
        "other": ("Notice the details at {place}", [
            "Walk to {place}.",
            "Find three details most people walk past.",
            "Guess how old the place is, then walk back a different way.",
        ], "Somewhere with something new to notice."),
    },
    "restless": {
        "green": ("Brisk loop to {place}", [
            "Walk briskly to {place}.",
            "Do two full laps at a pace that makes you breathe harder.",
            "Walk back easy and let your shoulders drop.",
        ], "Far enough to use up some energy."),
        "other": ("Walk it off to {place}", [
            "Walk to {place} a little faster than usual.",
            "Take the stairs or the longer side if there is one.",
            "Walk back slowly.",
        ], "Far enough to use up some energy."),
    },
    "social": {
        "green": ("Meet up at {place}", [
            "Walk to {place} together.",
            "Each pick one thing you spot that the others missed.",
            "Sit for a few minutes and talk about anything except screens.",
        ], "A shared green space with room for a group."),
        "other": ("Wander {place} together", [
            "Walk to {place} together.",
            "Take turns choosing which way to go once you're there.",
            "Walk back together without checking your phones.",
        ], "Easy to reach together."),
    },
}


def activity(c: Candidate, prefs: Prefs) -> GemmaPick:
    group = "green" if c.place.kind in GREEN else "other"
    title, steps, why = TEMPLATES[prefs.mood][group]
    if prefs.company == "others" and prefs.mood != "social":
        steps = [s.replace("you can't", "none of you can") for s in steps]
    duration = max(5, min(prefs.minutes - 2 * c.walk_min, 30))
    return GemmaPick(place_id=c.id, title=title, steps=list(steps), duration_min=duration, why=why)
