"""Guardie fail-fast all'avvio in produzione (Bloccanti B1/B4)."""
import os


def assert_production_safe() -> None:
    from src.core.security.docs import is_production

    if not is_production():
        return
    demo = os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
    if demo:
        raise RuntimeError(
            "AVVIO BLOCCATO: DEMO_MODE attivo con APP_ENV=production (B1). "
            "Rimuovi DEMO_MODE dalla configurazione di produzione."
        )
