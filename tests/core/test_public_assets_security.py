"""Guardrail di sicurezza per gli asset statici pubblici (/config.js, landing, auth).

Verifica che nessun secret, chiave privata, token sensibile o credenziale
venga mai esposto nei file serviti da Nginx al di fuori del gate di autenticazione.
"""
import re
from pathlib import Path
import pytest

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"

FORBIDDEN_SECRET_PATTERNS = [
    re.compile(r"sk_live_[0-9a-zA-Z]{24,}", re.IGNORECASE),
    re.compile(r"sk_test_[0-9a-zA-Z]{24,}", re.IGNORECASE),
    re.compile(r"service_role", re.IGNORECASE),
    re.compile(r"SUPABASE_SERVICE_ROLE_KEY", re.IGNORECASE),
    re.compile(r"PRIVATE\s+KEY", re.IGNORECASE),
    re.compile(r"ENCRYPTION_KEY", re.IGNORECASE),
    re.compile(r"API_KEY_SERVICE", re.IGNORECASE),
    re.compile(r"STRIPE_WEBHOOK_SECRET", re.IGNORECASE),
    re.compile(r"META_APP_SECRET\s*=", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),  # JWT
]

ALLOWED_CONFIG_EXPRESSIONS = [
    re.compile(r'^\s*window\.MELPIS_API_BASE\s*=\s*["\'][^"\']*["\'];?\s*$'),
    re.compile(r'^\s*window\.MELPIS_API_BASE\s*=\s*["\']\$\{MELPIS_API_BASE\}["\'];?\s*$'),
]


def test_config_js_contains_only_melpis_api_base():
    """Garantisce che config.template.js (e config.js se presente) contenga unicamente l'assegnazione di MELPIS_API_BASE."""
    template_file = WEB_ROOT / "config.template.js"
    assert template_file.exists(), f"{template_file} non trovato"

    config_files = [template_file]
    config_js = WEB_ROOT / "config.js"
    if config_js.exists():
        config_files.append(config_js)

    for config_file in config_files:
        content = config_file.read_text(encoding="utf-8")
        
        # Rimuove commenti su singola linea (//) e multi-line (/* ... */)
        code_without_block_comments = re.sub(r"/\*[\s\S]*?\*/", "", content)
        code_lines = [
            line.strip() for line in code_without_block_comments.splitlines()
            if line.strip() and not line.strip().startswith("//")
        ]
        
        # Deve esserci esattamente 1 riga eseguibile
        assert len(code_lines) == 1, (
            f"{config_file.name} contiene più di una riga di codice eseguibile: {code_lines}"
        )
        
        executable_line = code_lines[0]
        matches_allowed = any(pattern.match(executable_line) for pattern in ALLOWED_CONFIG_EXPRESSIONS)
        assert matches_allowed, (
            f"{config_file.name} contiene un'espressione non consentita: '{executable_line}'. "
            f"È consentita unicamente l'assegnazione di window.MELPIS_API_BASE."
        )


def test_no_secrets_in_public_web_assets():
    """Scansiona tutti i file statici pubblici serviti fuori da /app/ per pattern di secret."""
    public_paths = [
        WEB_ROOT / "config.js",
        WEB_ROOT / "config.template.js",
        WEB_ROOT / "login.html",
        WEB_ROOT / "login.js",
        WEB_ROOT / "register.html",
        WEB_ROOT / "register.js",
        WEB_ROOT / "auth.js",
        WEB_ROOT / "auth.css",
        *(WEB_ROOT / "landing").glob("*.html"),
        *(WEB_ROOT / "landing").glob("*.js"),
        *(WEB_ROOT / "landing").glob("*.css"),
    ]
    
    violations = []
    for file_path in public_paths:
        if not file_path.is_file():
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                violations.append(f"{file_path.name}: match vietato '{match.group(0)}' con pattern {pattern.pattern}")
                
    assert not violations, f"Rilevati pattern sensibili in file pubblici:\n" + "\n".join(violations)


def test_html_references_public_config_js():
    """Verifica che tutte le pagine HTML carichino /config.js e non /app/config.js."""
    html_files = [
        WEB_ROOT / "login.html",
        WEB_ROOT / "register.html",
        WEB_ROOT / "index.html",
    ]
    for html_file in html_files:
        assert html_file.exists()
        content = html_file.read_text(encoding="utf-8")
        assert "/app/config.js" not in content, (
            f"{html_file.name} referenzia ancora il vecchio path protetto '/app/config.js'"
        )
        assert '<script src="/config.js"></script>' in content, (
            f"{html_file.name} non include '<script src=\"/config.js\"></script>'"
        )
