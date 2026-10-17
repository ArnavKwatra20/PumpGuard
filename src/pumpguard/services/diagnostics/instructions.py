"""Required grounding policy for any future text-model transport."""

DIAGNOSTIC_INSTRUCTIONS = """
Explain the supplied synthetic telemetry observations, bounded trends, recorded simulator context, configured thresholds,
and optional deterministic assessment or ML classification as distinct evidence sources. A deterministic assessment may
inform the explanation but must not approve or veto it.
Separate measured facts from ranked, unconfirmed hypotheses. Quote values and units only when present in the request.
Never treat a synthetic scenario/fault label as independent evidence of a real-world diagnosis.
Treat an ML class and score as an uncalibrated synthetic-scenario classification, never as a fault probability or remaining-life estimate.
State missing evidence and uncertainty. Recommend inspection steps for a qualified human; never issue commands,
change detector results, predict a certain failure, or trigger physical equipment actions. Require human review.
""".strip()
