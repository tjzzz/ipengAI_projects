"""AI-analysis result helper (risk level)."""


def derive_risk_level(ai_score):
    """Derive risk level from AI score without running full analysis."""
    if not ai_score:
        return "Unknown"
    if ai_score < 20:
        return "Safe"
    elif ai_score < 40:
        return "Warning"
    elif ai_score < 60:
        return "Moderate Risk"
    else:
        return "High Risk"
