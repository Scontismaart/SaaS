import httpx
import logging
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from src.whatsapp.config import TenantConfig
from src.whatsapp.models import SendTextRequest, SendTemplateRequest, SendResponse

logger = logging.getLogger(__name__)


def _is_retryable_error(exception):
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code == 429
    # Ambiguous read/write timeouts and 5xx may follow an accepted POST.
    # Retrying those here bypasses the application's outbound claim.
    return isinstance(exception, (httpx.ConnectTimeout, httpx.ConnectError))


class MetaClient:
    BASE_URL = "https://graph.facebook.com/v20.0"

    def __init__(self, tenant_config: TenantConfig):
        self.phone_number_id = tenant_config.phone_number_id
        self.access_token = tenant_config.access_token
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
    async def send_message(self, payload: SendTextRequest | SendTemplateRequest) -> SendResponse:
        url = f"/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        data = payload.model_dump(exclude_none=True)
        try:
            response = await self._client.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = SendResponse.model_validate(response.json())
            if not result.messages or not result.messages[0].id:
                raise ValueError("Missing provider message ID")
            return result
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Meta API error: status=%d",
                exc.response.status_code,
            )
            raise httpx.HTTPStatusError(
                f"Meta API returned HTTP {exc.response.status_code}",
                request=exc.request, response=exc.response,
            ) from None
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("Meta API transport error: type=%s", type(exc).__name__)
            raise type(exc)("Meta API transport failure") from None
        except ValueError:
            raise ValueError("Meta API returned an invalid response") from None
