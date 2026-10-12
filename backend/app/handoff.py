"""Human-handoff decision engine.

A conversation is transferred to a human when one or more signals fire.
Sentiment is only one of them.
"""
from dataclasses import dataclass, field

from .config import LOW_CONFIDENCE_THRESHOLD, MAX_FAILED_ATTEMPTS, NEGATIVE_SENTIMENT_THRESHOLD


@dataclass
class HandoffDecision:
    handoff: bool
    reasons: list[str] = field(default_factory=list)
    priority: str = "normal"


def evaluate(sentiment: float, recent_sentiments: list[float], confidence: float, failed_attempts: int,
             customer_asked_for_human: bool, needs_approval: bool, repeated_injection: bool) -> HandoffDecision:
    reasons = []
    if customer_asked_for_human:
        reasons.append("customer_requested_human")
    if sentiment <= NEGATIVE_SENTIMENT_THRESHOLD:
        reasons.append("strong_negative_sentiment")
    # sustained frustration: the last three customer messages are all negative
    elif len(recent_sentiments) >= 3 and all(s < -0.2 for s in recent_sentiments[-3:]):
        reasons.append("sustained_negative_sentiment")
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        reasons.append("low_ai_confidence")
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        reasons.append("unsuccessful_resolution")
    if needs_approval:
        reasons.append("action_requires_human_approval")
    if repeated_injection:
        reasons.append("repeated_security_violation")

    # low confidence on its own does not escalate: the agent first asks the customer to clarify.
    # Repeated misunderstandings are caught by the unsuccessful_resolution rule.
    if reasons == ["low_ai_confidence"]:
        return HandoffDecision(False, reasons)

    high = {"strong_negative_sentiment", "action_requires_human_approval", "repeated_security_violation"}
    priority = "high" if high & set(reasons) else "normal"
    return HandoffDecision(bool(reasons), reasons, priority)
