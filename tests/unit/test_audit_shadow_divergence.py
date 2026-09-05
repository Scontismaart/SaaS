import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_shadow_divergence import (
    ShadowAuditEvent,
    evaluate_shadow_audit,
    parse_shadow_logs,
)


def test_parse_shadow_logs_extracts_cleanly():
    log_lines = [
        "2026-09-05 12:00:01 INFO src.core.inbound.service [SHADOW_ORCHESTRATOR] msg_id=msg-1 legacy_len=120 orch_len=115 orch_source=rag_context channel=whatsapp",
        "2026-09-05 12:00:02 INFO src.core.inbound.service [SHADOW_ORCHESTRATOR] msg_id=msg-2 legacy_len=80 orch_len=85 orch_source=faq_cache channel=instagram",
        "2026-09-05 12:00:03 INFO other log line to ignore",
        "2026-09-05 12:00:04 WARNING src.core.inbound.service [SHADOW_ORCHESTRATOR] Comparison error: Connection timeout to RAG",
    ]

    events, errors = parse_shadow_logs(log_lines)
    assert len(events) == 2
    assert len(errors) == 1
    assert errors[0] == "Connection timeout to RAG"

    ev1 = events[0]
    assert ev1.msg_id == "msg-1"
    assert ev1.legacy_len == 120
    assert ev1.orch_len == 115
    assert ev1.orch_source == "rag_context"
    assert ev1.channel == "whatsapp"
    assert not ev1.is_truncated
    assert not ev1.is_runaway
    assert not ev1.is_high_divergence


def test_evaluate_go_verdict_when_all_criteria_met():
    # 10 consistent events, no errors, delta < 20%
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-{i}",
            legacy_len=100,
            orch_len=105,
            orch_source="faq_cache",
            channel="whatsapp",
        )
        for i in range(12)
    ]
    summary = evaluate_shadow_audit(events, errors=[], min_samples=10, max_divergence_pct=5.0)

    assert summary.verdict == "GO (ELIGIBLE FOR PURGE)"
    assert summary.total_events == 12
    assert summary.total_errors == 0
    assert summary.truncation_count == 0
    assert summary.runaway_count == 0
    assert summary.high_divergence_count == 0
    assert len(summary.reasons) == 0


def test_evaluate_nogo_on_comparison_error():
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-{i}",
            legacy_len=100,
            orch_len=100,
            orch_source="faq_cache",
        )
        for i in range(15)
    ]
    summary = evaluate_shadow_audit(
        events, errors=["LLM timeout during shadow run"], min_samples=10
    )

    assert summary.verdict == "NO-GO (HARD BLOCKED)"
    assert any("Errori di comparazione presenti" in r for r in summary.reasons)


def test_evaluate_nogo_on_truncation():
    # 1 event has legacy_len=120, orch_len=5 (<10)
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-{i}",
            legacy_len=100,
            orch_len=100,
            orch_source="faq_cache",
        )
        for i in range(14)
    ] + [
        ShadowAuditEvent(
            msg_id="msg-fail",
            legacy_len=120,
            orch_len=4,
            orch_source="rag_context",
        )
    ]
    summary = evaluate_shadow_audit(events, errors=[], min_samples=10)

    assert summary.verdict == "NO-GO (HARD BLOCKED)"
    assert summary.truncation_count == 1
    assert any("Risposte troncate/vuote rilevate" in r for r in summary.reasons)


def test_evaluate_nogo_on_runaway_verbosity():
    # 1 event has legacy_len=60, orch_len=350 (>4x)
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-{i}",
            legacy_len=100,
            orch_len=100,
            orch_source="faq_cache",
        )
        for i in range(14)
    ] + [
        ShadowAuditEvent(
            msg_id="msg-runaway",
            legacy_len=60,
            orch_len=350,
            orch_source="rag_context",
        )
    ]
    summary = evaluate_shadow_audit(events, errors=[], min_samples=10)

    assert summary.verdict == "NO-GO (HARD BLOCKED)"
    assert summary.runaway_count == 1
    assert any("Verbosita anomala fuori scala rilevata" in r for r in summary.reasons)


def test_evaluate_nogo_on_excessive_high_divergence_percentage():
    # 10 events: 8 within 10%, 2 with delta ratio > 0.50 -> 20% > 5% threshold
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-ok-{i}",
            legacy_len=100,
            orch_len=102,
            orch_source="faq_cache",
        )
        for i in range(8)
    ] + [
        ShadowAuditEvent(
            msg_id="msg-div-1",
            legacy_len=100,
            orch_len=160,  # 60% delta, abs=60 >= 25, max=160 >= 40
            orch_source="rag_context",
        ),
        ShadowAuditEvent(
            msg_id="msg-div-2",
            legacy_len=100,
            orch_len=40,   # 60% delta, abs=60 >= 25, max=100 >= 40
            orch_source="rag_context",
        ),
    ]
    summary = evaluate_shadow_audit(events, errors=[], min_samples=10, max_divergence_pct=5.0)

    assert summary.verdict == "NO-GO (HUMAN REVIEW REQUIRED)"
    assert summary.high_divergence_count == 2
    assert summary.high_divergence_pct == 20.0
    assert any("Tasso di divergenza elevata" in r for r in summary.reasons)


def test_evaluate_nogo_on_insufficient_samples():
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-{i}",
            legacy_len=100,
            orch_len=100,
            orch_source="faq_cache",
        )
        for i in range(5)
    ]
    summary = evaluate_shadow_audit(events, errors=[], min_samples=10)

    assert summary.verdict == "NO-GO (HARD BLOCKED)"
    assert any("Campione insufficiente" in r for r in summary.reasons)


def test_short_strings_below_floor_not_flagged_as_high_divergence():
    # 20 chars vs 31 chars: ratio is 11/20 = 55% (>50%), but max(20, 31) < 40 and delta is 11 (<25)
    short_ev = ShadowAuditEvent(
        msg_id="short-1",
        legacy_len=20,
        orch_len=31,
        orch_source="faq_cache",
    )
    assert short_ev.delta_ratio == 0.55
    assert not short_ev.is_high_divergence

    # 35 chars vs 55 chars: max >= 40, but abs(55-35)=20 < 25 -> not high divergence
    border_ev = ShadowAuditEvent(
        msg_id="border-1",
        legacy_len=35,
        orch_len=55,
        orch_source="faq_cache",
    )
    assert not border_ev.is_high_divergence

    # 50 chars vs 85 chars: max=85 >= 40, delta=35 >= 25, ratio=35/50 = 0.70 > 0.50 -> high divergence!
    real_div_ev = ShadowAuditEvent(
        msg_id="real-1",
        legacy_len=50,
        orch_len=85,
        orch_source="rag_context",
    )
    assert real_div_ev.is_high_divergence


def test_human_review_override_approves_soft_divergence():
    # 10 events with 2 high divergence (20% > 5%)
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-ok-{i}",
            legacy_len=100,
            orch_len=102,
            orch_source="faq_cache",
        )
        for i in range(8)
    ] + [
        ShadowAuditEvent(
            msg_id="msg-div-1",
            legacy_len=100,
            orch_len=160,
            orch_source="rag_context",
        ),
        ShadowAuditEvent(
            msg_id="msg-div-2",
            legacy_len=100,
            orch_len=40,
            orch_source="rag_context",
        ),
    ]
    summary = evaluate_shadow_audit(
        events,
        errors=[],
        min_samples=10,
        max_divergence_pct=5.0,
        reviewer="lead_architect",
        rationale="Orchestrator prompt has slightly richer politeness formula on complex FAQs; intent fully aligned.",
    )

    assert summary.verdict == "GO (APPROVED VIA HUMAN REVIEW)"
    assert summary.human_override is not None
    assert summary.human_override["reviewer"] == "lead_architect"
    assert "richer politeness formula" in summary.human_override["rationale"]
    assert "approved_at" in summary.human_override
    assert len(summary.reasons) == 0


def test_human_review_override_strictly_blocks_on_hard_failures():
    # Even with human reviewer and rationale, a hard failure (comparison error) CANNOT be bypassed
    events = [
        ShadowAuditEvent(
            msg_id=f"msg-ok-{i}",
            legacy_len=100,
            orch_len=102,
            orch_source="faq_cache",
        )
        for i in range(12)
    ]
    summary = evaluate_shadow_audit(
        events,
        errors=["Uncaught Exception in RAG lookup"],
        min_samples=10,
        reviewer="lead_architect",
        rationale="Attempting to override error",
    )

    assert summary.verdict == "NO-GO (HARD BLOCKED)"
    assert any("Errori di comparazione presenti" in r for r in summary.reasons)
    assert any("Tentativo di override umano respinto" in r for r in summary.reasons)

    from scripts.audit_shadow_divergence import format_report
    report_text = format_report(summary, max_divergence_pct=5.0)
    assert "NOTA CRITICA SULLA CLAUSOLA 'HARD BLOCKED'" in report_text
    assert "tentativo di override umano e stato RESPINTO" in report_text

