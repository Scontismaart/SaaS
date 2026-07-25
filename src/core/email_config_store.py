import os
import json

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "email_config.json"
)


def _carica_tutti() -> list[dict]:
    if not os.path.exists(_CONFIG_PATH):
        return []
    try:
        with open(_CONFIG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _salva_tutti(configs: list[dict]):
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w") as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)


def salva_config(indirizzo: str):
    configs = _carica_tutti()
    for c in configs:
        if c["indirizzo"] == indirizzo:
            _salva_tutti(configs)
            return
    configs.append({"indirizzo": indirizzo})
    _salva_tutti(configs)


def carica_config(indirizzo: str | None = None) -> list[dict]:
    configs = _carica_tutti()
    if indirizzo:
        return [c for c in configs if c["indirizzo"] == indirizzo]
    return configs


def elenca_config() -> list[dict]:
    return _carica_tutti()


def elimina_config(indirizzo: str) -> bool:
    configs = _carica_tutti()
    nuovi = [c for c in configs if c["indirizzo"] != indirizzo]
    if len(nuovi) == len(configs):
        return False
    _salva_tutti(nuovi)
    return True


def inizializza():
    pass
