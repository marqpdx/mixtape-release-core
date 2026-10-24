"""Heddle — the shared interpretation service (ADR-0061).

Turns a surface's raw material into provisional, checked Contour
Sightings. Sits between Loom's Execution and Memory parts; uses Routing
(Switchboard) and Provenance (ActionRuns). Owns the mechanics every
surface needs (source/fingerprint, exact spans, provenance, stale-result
rejection, consent-before-dispatch); each surface owns its own Shape and
meaning checks (D7) and its own resolution against its own records (D6).

Shuttle (ADR-0058) is its first caller (HD-2); Folio (ADR-0060) is the
second, which is this module's actual second-consumer test.
"""
