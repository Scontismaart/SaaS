import httpx
import logging
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from src.whatsapp.client import _is_retryable_error
from src.instagram.models import IgSendTextRequest, IgSendResponse

logger = logging.getLogger(__name__)


class InstagramClient:
    """Invio DM via Instagram Graph API. Condivide con MetaClient la stessa
    base URL Graph, la policy di retry (importata da src.whatsapp.client per
    non duplicare la logica di retryable-error in giro per il codebase) e il
    pattern httpx.AsyncClient per-istanza."""

    BASE_URL = "https://graph.facebook.com/v20.0"

    def __init__(self, ig_user_id: str, access_token: str):
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0, read=10.0),
        )

    async def close(self):
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def send_message(self, payload: IgSendTextRequest) -> IgSendResponse:
        url = f"/{self.ig_user_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        data = payload.model_dump(exclude_none=True)
        try:
            response = await self._client.post(url, headers=headers, json=data)
            response.raise_for_status()
            return IgSendResponse.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Instagram API error: status=%d body=%s",
                exc.response.status_code, exc.response.text,
            )
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("Instagram API error: %s", exc)
            raise
