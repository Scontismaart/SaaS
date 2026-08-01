from src.core.review_sources.base import FonteRecensioni
from src.models.schemas import RecensioneInput


class FonteGoogle(FonteRecensioni):
    """Fonte Google Business Profile.

    Il fetch delle review passa da GoogleBusinessService (OAuth + API
    ufficiale mybusiness, niente scraping). Il polling periodico richiede
    le credenziali dell'org: per questo il sync viene triggerato via
    endpoint (POST /api/reviews/google/sync) e qui resta un adattatore
    che delega al service quando le credenziali sono disponibili.
    """

    def __init__(self, service=None, organization_id=None):
        self._service = service
        self._organization_id = organization_id

    def recupera_nuove_recensioni(self) -> list[RecensioneInput]:
        if self._service is None or self._organization_id is None:
            return []
        import asyncio
        try:
            asyncio.run(self._service.fetch_reviews(self._organization_id))
        except Exception:
            return []
        # fetch_reviews persiste gia' le review nel DB; il ritorno qui e'
        # solo informativo (quante nuove sono state inserite).
        return []
