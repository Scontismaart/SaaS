#!/usr/bin/env python3
"""
Script di audit automatizzato pre-purge per il Sunset della Quarantena Legacy (Scadenza: 2026-09-19).

Analizza i log applicativi della Shadow Mode ([SHADOW_ORCHESTRATOR]) e applica
soglie numeriche matematiche e deterministiche per emettere un verdetto GO / NO-GO.

Criteri di Uscita Tassativi (Gate di Purge):
1. Errori di comparazione (eccezioni/crash): 0 tollerati (Soglia: == 0).
2. Troncamenti anomali (legacy_len >= 30 ma orch_len < 10): 0 tollerati (Soglia: == 0).
3. Verbosità fuori controllo (orch_len > 4 * legacy_len o orch_len > 2500): 0 tollerati (Soglia: == 0).
4. Tasso di divergenza elevata (R = |orch_len - legacy_len| / max(legacy_len, 1) > 0.50): max 5.0%.
5. Volume minimo di campionamento (min_samples, default 10 per staging/test, 50 per prod).

Uso:
  python scripts/audit_shadow_divergence.py --log-file app.log
  cat app.log | python scripts/audit_shadow_divergence.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

# Regex per eventi shadow normali
EVENT_RE = re.compile(
    r"\[SHADOW_ORCHESTRATOR\]\s+msg_id=(?P<msg_id>[^\s]+)\s+legacy_len=(?P<legacy_len>\d+)\s+orch_len=(?P<orch_len>\d+)\s+orch_source=(?P<orch_source>[^\s]+)(?:\s+channel=(?P<channel>[^\s]+))?"
)

# Regex per errori ed eccezioni nella shadow mode
ERROR_RE = re.compile(r"\[SHADOW_ORCHESTRATOR\]\s+Comparison error:\s+(?P<error>.*)")


@dataclass(frozen=True)
class ShadowAuditEvent:
    msg_id: str
    legacy_len: int
    orch_len: int
    orch_source: str
    channel: str = "whatsapp"

    @property
    def delta(self) -> int:
        return self.orch_len - self.legacy_len

    @property
    def delta_ratio(self) -> float:
        denom = max(self.legacy_len, 1)
        return abs(self.orch_len - self.legacy_len) / denom

    @property
    def is_truncated(self) -> bool:
        """Risposta orchestratore vuota o troncata a fronte di risposta legacy valida."""
        return self.legacy_len >= 30 and self.orch_len < 10

    @property
    def is_runaway(self) -> bool:
        """Risposta orchestratore verbosa fuori scala o eccedente limite canale."""
        if self.orch_len > 2500:
            return True
        if self.legacy_len >= 50 and self.orch_len > 4 * self.legacy_len:
            return True
        return False

    @property
    def is_high_divergence(self) -> bool:
        """
        Delta superiore al 50% rispetto alla lunghezza legacy.
        Per prevenire falsi positivi su risposte FAQ o frasi brevi (es. 15-30 caratteri),
        si applica un floor minimo: richiede lunghezza massima >= 40 caratteri E
        una differenza assoluta di almeno 25 caratteri.
        """
        if max(self.legacy_len, self.orch_len) < 40:
            return False
        if abs(self.orch_len - self.legacy_len) < 25:
            return False
        return self.delta_ratio > 0.50


@dataclass
class ShadowAuditSummary:
    total_events: int = 0
    total_errors: int = 0
    truncation_count: int = 0
    runaway_count: int = 0
    high_divergence_count: int = 0
    sources_breakdown: dict[str, int] = field(default_factory=dict)
    channels_breakdown: dict[str, int] = field(default_factory=dict)
    error_messages: list[str] = field(default_factory=list)
    verdict: str = "PENDING"
    reasons: list[str] = field(default_factory=list)
    human_override: dict[str, str] | None = None

    @property
    def high_divergence_pct(self) -> float:
        if self.total_events == 0:
            return 0.0
        return (self.high_divergence_count / self.total_events) * 100.0


def parse_shadow_logs(lines: Iterable[str]) -> tuple[list[ShadowAuditEvent], list[str]]:
    events: list[ShadowAuditEvent] = []
    errors: list[str] = []

    for line in lines:
        ev_match = EVENT_RE.search(line)
        if ev_match:
            d = ev_match.groupdict()
            events.append(
                ShadowAuditEvent(
                    msg_id=d["msg_id"],
                    legacy_len=int(d["legacy_len"]),
                    orch_len=int(d["orch_len"]),
                    orch_source=d["orch_source"],
                    channel=d.get("channel") or "whatsapp",
                )
            )
            continue

        err_match = ERROR_RE.search(line)
        if err_match:
            errors.append(err_match.group("error").strip())

    return events, errors


def evaluate_shadow_audit(
    events: Sequence[ShadowAuditEvent],
    errors: Sequence[str],
    min_samples: int = 10,
    max_divergence_pct: float = 5.0,
    reviewer: str | None = None,
    rationale: str | None = None,
) -> ShadowAuditSummary:
    summary = ShadowAuditSummary()
    summary.total_events = len(events)
    summary.total_errors = len(errors)
    summary.error_messages = list(errors)

    for ev in events:
        if ev.is_truncated:
            summary.truncation_count += 1
        if ev.is_runaway:
            summary.runaway_count += 1
        if ev.is_high_divergence:
            summary.high_divergence_count += 1

        summary.sources_breakdown[ev.orch_source] = (
            summary.sources_breakdown.get(ev.orch_source, 0) + 1
        )
        summary.channels_breakdown[ev.channel] = (
            summary.channels_breakdown.get(ev.channel, 0) + 1
        )

    # Valutazione criteri tassativi
    hard_failures: list[str] = []
    soft_failures: list[str] = []

    if summary.total_events < min_samples:
        hard_failures.append(
            f"Campione insufficiente: {summary.total_events} eventi registrati (minimo richiesto: {min_samples})"
        )

    if summary.total_errors > 0:
        hard_failures.append(
            f"Errori di comparazione presenti: {summary.total_errors} eccezioni rilevate (tolleranza: 0)"
        )

    if summary.truncation_count > 0:
        hard_failures.append(
            f"Risposte troncate/vuote rilevate: {summary.truncation_count} occorrenze (tolleranza: 0)"
        )

    if summary.runaway_count > 0:
        hard_failures.append(
            f"Verbosita anomala fuori scala rilevata: {summary.runaway_count} occorrenze (tolleranza: 0)"
        )

    if reviewer and rationale:
        import datetime
        summary.human_override = {
            "reviewer": reviewer,
            "rationale": rationale,
            "approved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    divergence_flagged = summary.high_divergence_pct > max_divergence_pct
    if divergence_flagged and not summary.human_override:
        soft_failures.append(
            f"Tasso di divergenza elevata: {summary.high_divergence_pct:.1f}% > soglia max {max_divergence_pct:.1f}% "
            "(richiede firma formale con --reviewer e --rationale)"
        )

    all_failures = hard_failures + soft_failures
    if hard_failures:
        summary.verdict = "NO-GO (HARD BLOCKED)"
        if summary.human_override:
            all_failures.append(
                "CLAUSOLA HARD BLOCKED ATTIVA: Tentativo di override umano respinto. "
                "Errori di comparazione, troncamenti, verbosita runaway o campioni insufficienti "
                "NON sono mai derogabili con --reviewer / --rationale."
            )
    elif soft_failures:
        summary.verdict = "NO-GO (HUMAN REVIEW REQUIRED)"
    elif summary.human_override:
        summary.verdict = "GO (APPROVED VIA HUMAN REVIEW)"
    else:
        summary.verdict = "GO (ELIGIBLE FOR PURGE)"

    summary.reasons = all_failures
    return summary


def format_report(summary: ShadowAuditSummary, max_divergence_pct: float) -> str:
    lines = [
        "=" * 80,
        "REPORT DI AUDIT SHADOW MODE - VERIFICA PRE-PURGE LEGACY PIPELINE",
        "=" * 80,
        f"Verdetto Finale:                   [{summary.verdict}]",
        f"Eventi Totali Campionati:           {summary.total_events}",
        f"Errori / Eccezioni di Comparazione: {summary.total_errors} (Soglia: 0)",
        f"Risposte Troncate / Vuote:         {summary.truncation_count} (Soglia: 0)",
        f"Verbosita Fuori Controllo (>4x):   {summary.runaway_count} (Soglia: 0)",
        f"Divergenza Elevata (Delta > 50%):  {summary.high_divergence_count} ({summary.high_divergence_pct:.1f}%) (Soglia Max: {max_divergence_pct:.1f}%)",
        "-" * 80,
        "Distribuzione Sorgenti Risposta (orch_source):",
    ]
    for src, count in sorted(summary.sources_breakdown.items()):
        lines.append(f"  - {src:20s}: {count} ({count / max(summary.total_events, 1) * 100:.1f}%)")

    lines.append("Distribuzione Canali:")
    for chan, count in sorted(summary.channels_breakdown.items()):
        lines.append(f"  - {chan:20s}: {count} ({count / max(summary.total_events, 1) * 100:.1f}%)")

    if summary.human_override:
        lines.append("-" * 80)
        lines.append("APPROVAZIONE UMANA REGISTRATA:")
        lines.append(f"  - Revisore:     {summary.human_override['reviewer']}")
        lines.append(f"  - Motivazione:  {summary.human_override['rationale']}")
        lines.append(f"  - Data/Ora:     {summary.human_override['approved_at']}")

    if summary.verdict == "NO-GO (HARD BLOCKED)":
        lines.append("-" * 80)
        lines.append("NOTA CRITICA SULLA CLAUSOLA 'HARD BLOCKED':")
        lines.append("  [!] Questo verdetto e TASSATIVO e NON puo essere scavalcato con --reviewer o --rationale.")
        lines.append("      I fallimenti gravi (errori runtime/timeout, risposte troncate/vuote, verbosita fuori scala,")
        lines.append("      o campionamento insufficiente) costituiscono un blocco di sicurezza strutturale.")
        lines.append("      La firma umana con --reviewer e consentita ESCLUSIVAMENTE per divergenze di lunghezza (soft failure).")
        if summary.human_override:
            lines.append("  [X] ATTENZIONE: Il tentativo di override umano e stato RESPINTO a causa delle violazioni gravi sopra indicate.")

    if summary.reasons:
        lines.append("-" * 80)
        lines.append("MOTIVAZIONI DETTAGLIATE:")
        for r in summary.reasons:
            lines.append(f"  [X] {r}")
    elif not summary.human_override:
        lines.append("-" * 80)
        lines.append("Tutti i criteri tassativi sono pienamente soddisfatti. Autorizzazione al purge concessa.")

    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Audit automatizzato shadow mode per verdetto di purge pre-sunset."
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Percorso al file di log applicativo. Se non specificato, legge da stdin.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=10,
        help="Numero minimo di eventi shadow richiesti per dichiarare valido l'audit (default: 10).",
    )
    parser.add_argument(
        "--max-divergence-pct",
        type=float,
        default=5.0,
        help="Percentuale massima tollerata di eventi con delta maggiore del 50 percento (default: 5.0).",
    )
    parser.add_argument(
        "--reviewer",
        type=str,
        default=None,
        help=(
            "Identificativo del revisore umano. NOTA TASSATIVA: Efficace ESCLUSIVAMENTE per divergenze di lunghezza "
            "(soft failure >5%%). Non ha alcun effetto sui fallimenti gravi (errori runtime, risposte troncate, "
            "verbosita runaway, campionamento insufficiente), i quali generano sempre HARD BLOCKED senza possibilita di deroga."
        ),
    )
    parser.add_argument(
        "--rationale",
        type=str,
        default=None,
        help="Motivazione tecnica registrata per l'approvazione formale della divergenza di lunghezza.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Stampa l'output in formato JSON invece del report testuale.",
    )

    args = parser.parse_args()

    if args.log_file:
        try:
            with open(args.log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            sys.stderr.write(f"Errore apertura file log {args.log_file}: {e}\n")
            sys.exit(2)
    else:
        if sys.stdin.isatty():
            sys.stderr.write("Nessun input fornito su stdin o --log-file.\n")
            sys.exit(2)
        lines = sys.stdin.readlines()

    events, errors = parse_shadow_logs(lines)
    summary = evaluate_shadow_audit(
        events,
        errors,
        min_samples=args.min_samples,
        max_divergence_pct=args.max_divergence_pct,
        reviewer=args.reviewer,
        rationale=args.rationale,
    )

    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(format_report(summary, args.max_divergence_pct))

    # Exit code: 0 = GO, 1 = NO-GO
    sys.exit(0 if summary.verdict.startswith("GO") else 1)


if __name__ == "__main__":
    main()
