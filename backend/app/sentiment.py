"""Lexicon-based sentiment analyser.

Score range is -1.0 (very negative) to +1.0 (very positive). It handles negation
("not happy"), intensifiers ("very angry"), exclamation marks and shouting (CAPS).
It runs locally, so every message gets a deterministic score even without an LLM.
"""
import math
import re

LEXICON = {
    # negative
    "angry": -3, "furious": -4, "annoyed": -2, "frustrated": -3, "frustrating": -3, "upset": -2.5,
    "disappointed": -2.5, "disappointing": -2.5, "terrible": -3, "horrible": -3, "awful": -3, "worst": -3.5,
    "bad": -2, "poor": -2, "useless": -3, "rubbish": -3, "nonsense": -2.5, "scam": -3.5, "fraud": -3.5,
    "cheat": -3, "cheated": -3, "stolen": -3, "robbed": -3.5, "never": -1, "late": -1.5, "delayed": -1.5,
    "wrong": -1.5, "broken": -2, "damaged": -2, "missing": -1.5, "problem": -1, "issue": -0.5,
    "complaint": -1.5, "hate": -3, "ridiculous": -3, "unacceptable": -3, "waste": -2.5, "wasted": -2.5,
    "tired": -1.5, "fed": -1, "stupid": -3, "incompetent": -3, "lie": -2.5, "lied": -3, "lying": -3,
    "sue": -3, "lawyer": -2, "report": -1, "refund": -0.5, "cancel": -0.5, "nobody": -1.5, "ignored": -2.5,
    "again": -0.5, "still": -0.5, "sick": -2, "joke": -1.5, "pathetic": -3.5, "disgusting": -3.5,
    # positive
    "thanks": 2, "thank": 2, "great": 3, "good": 2, "excellent": 3.5, "perfect": 3, "happy": 2.5,
    "love": 3, "awesome": 3, "amazing": 3, "helpful": 2.5, "nice": 2, "resolved": 2, "solved": 2,
    "appreciate": 2.5, "fine": 1, "ok": 0.5, "okay": 0.5, "cool": 1.5, "wonderful": 3, "fast": 1.5,
    "satisfied": 2.5, "pleased": 2.5, "glad": 2, "works": 1.5, "working": 1, "kind": 1.5,
}
NEGATIONS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't", "cant", "can't",
             "won't", "wont", "didnt", "didn't", "hardly"}
INTENSIFIERS = {"very": 1.5, "so": 1.4, "really": 1.4, "extremely": 1.8, "totally": 1.5, "completely": 1.5,
                "too": 1.3, "absolutely": 1.6, "super": 1.4}


def analyse(text: str) -> float:
    tokens = re.findall(r"[A-Za-z']+", text)
    total = 0.0
    for i, raw in enumerate(tokens):
        word = raw.lower()
        if word not in LEXICON:
            continue
        value = LEXICON[word]
        prev = [t.lower() for t in tokens[max(0, i - 3):i]]
        if any(p in NEGATIONS for p in prev):
            value *= -0.6
        if prev and prev[-1] in INTENSIFIERS:
            value *= INTENSIFIERS[prev[-1]]
        if raw.isupper() and len(raw) > 2:
            value *= 1.4
        total += value
    # emphasis from exclamation marks pushes the score further in its direction
    bangs = min(text.count("!"), 4)
    if total:
        total += math.copysign(0.3 * bangs, total)
    # overall shouting
    letters = [c for c in text if c.isalpha()]
    if len(letters) > 12 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        total -= 1.5
    # normalise to [-1, 1] (same normalisation used by VADER)
    return round(total / math.sqrt(total * total + 15), 3)


def label(score: float) -> str:
    if score <= -0.6:
        return "very negative"
    if score < -0.05:
        return "negative"
    if score > 0.05:
        return "positive"
    return "neutral"
