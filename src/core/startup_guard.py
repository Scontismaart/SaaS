"""Guardie fail-fast all'avvio in produzione (Bloccanti B1/B4)."""
import os


def assert_production_safe() -> None:
    from src.core.security.docs import is_production

    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    zero_cost = os.getenv("ZERO_COST_RELEASE", "true").strip().lower() != "false"
    if stripe_key.startswith("sk_live") and (not is_production() or zero_cost):
        raise RuntimeError(
            "AVVIO BLOCCATO: STRIPE_SECRET_KEY live non autorizzata nel profilo a costo zero."
        )
    if not is_production():
        return
    demo = os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
    if demo:
        raise RuntimeError(
            "AVVIO BLOCCATO: DEMO_MODE attivo con APP_ENV=production (B1). "
            "Rimuovi DEMO_MODE dalla configurazione di produzione."
        )
    if zero_cost:
        if os.getenv("LLM_COST_POLICY", "free_only") != "free_only":
            raise RuntimeError("AVVIO BLOCCATO: il rilascio EUR 0 richiede LLM_COST_POLICY=free_only")
        if os.getenv("GROQ_FREE_ACCOUNT_CONFIRMED", "").lower() != "true":
            raise RuntimeError("AVVIO BLOCCATO: account Groq FREE non confermato")
        if os.getenv("SANDBOX_ONLY", "true").lower() != "true":
            raise RuntimeError("AVVIO BLOCCATO: SANDBOX_ONLY deve restare true nel pre-lancio")
        if stripe_key and not stripe_key.startswith("sk_test_"):
            raise RuntimeError("AVVIO BLOCCATO: Stripe deve usare una chiave sk_test_ nel pre-lancio")
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
