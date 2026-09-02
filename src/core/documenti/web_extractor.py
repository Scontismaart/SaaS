"""
web_extractor.py
----------------
Recupero e parsing del contenuto testuale da pagine web pubbliche (URL).
Rimuove script, stili, intestazioni e navigazione per estrarre il testo principale.
"""

from html.parser import HTMLParser
import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse
import httpx

logger = logging.getLogger(__name__)

TAGS_DA_IGNORARE = {
    "script", "style", "nav", "footer", "header", "noscript",
    "svg", "iframe", "button", "input", "form", "select", "option"
}

MAX_WEB_BYTES = 5 * 1024 * 1024  # 5 MB


def _is_safe_host(hostname: str) -> bool:
    """Verifica che l'hostname non punti a localhost, IP privati o metadata cloud (SSRF)."""
    if not hostname:
        return False
    h = hostname.lower()
    if h in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return False
    try:
        ip = ipaddress.ip_address(h)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(h, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except (socket.gaierror, ValueError, OSError):
        return False


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tag_stack: list[str] = []
        self.text_parts: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()
        self.tag_stack.append(tag_lower)
        if tag_lower == "title":
            self._in_title = True
        elif tag_lower in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self._in_title = False
        if self.tag_stack and self.tag_stack[-1] == tag_lower:
            self.tag_stack.pop()
        elif tag_lower in self.tag_stack:
            while self.tag_stack and self.tag_stack[-1] != tag_lower:
                self.tag_stack.pop()
            if self.tag_stack:
                self.tag_stack.pop()
        if tag_lower in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str):
        if self._in_title and not self.title:
            self.title = data.strip()
        if any(ignored in self.tag_stack for ignored in TAGS_DA_IGNORARE):
            return
        cleaned = data.strip()
        if cleaned:
            self.text_parts.append(cleaned + " ")

    def get_text(self) -> str:
        raw = "".join(self.text_parts)
        # Normalizza righe multiple e spazi vuoti
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
        filtered = [l for l in lines if l]
        return "\n\n".join(filtered)


async def estrai_da_url(url: str, timeout: float = 15.0) -> dict[str, str]:
    """Scarica ed estrae il testo principale da una pagina web.

    Restituisce un dizionario con 'titolo', 'testo' e 'url'.
    Solleva ValueError in caso di URL non valido, SSRF, errore di rete o contenuto vuoto.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL non valido.")

    # Protezione anti-SSRF: blocca reti locali e link-local
    if not _is_safe_host(parsed.hostname):
        raise ValueError("Accesso a indirizzi locali o privati non consentito.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                raise ValueError(f"La pagina ha restituito lo stato HTTP {resp.status_code}.")

            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > MAX_WEB_BYTES:
                raise ValueError("La pagina supera la dimensione massima consentita (5 MB).")

            if len(resp.content) > MAX_WEB_BYTES:
                raise ValueError("La pagina supera la dimensione massima consentita (5 MB).")
            
            content_type = resp.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                if content_type.startswith("text/"):
                    testo = resp.text.strip()
                    if not testo:
                        raise ValueError("La pagina non contiene testo.")
                    return {"titolo": parsed.netloc, "testo": testo, "url": url}
                raise ValueError(f"Tipo di contenuto non supportato ({content_type}). L'URL deve puntare a una pagina web.")

            html_text = resp.text
    except httpx.RequestError as exc:
        raise ValueError(f"Impossibile raggiungere l'URL ({exc}). Verifica l'indirizzo e riprova.") from exc

    parser = _HTMLTextExtractor()
    parser.feed(html_text)
    testo = parser.get_text()

    if not testo or len(testo) < 30:
        raise ValueError("Non è stato possibile estrarre testo sufficiente dalla pagina web.")

    titolo = parser.title or parsed.netloc
    return {
        "titolo": titolo[:150],
        "testo": testo,
        "url": url,
    }
