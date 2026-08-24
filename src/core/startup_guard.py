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
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "AVVIO BLOCCATO: ENCRYPTION_KEY mancante in produzione (B4). "
            "Genera con: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    from cryptography.fernet import Fernet
    try:
        Fernet(key)
    except Exception as exc:
        raise RuntimeError(
            "AVVIO BLOCCATO: ENCRYPTION_KEY non e' una chiave Fernet valida (B4)."
        ) from exc
