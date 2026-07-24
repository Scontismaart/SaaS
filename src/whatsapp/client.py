import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from src.whatsapp.config import TenantConfig
from src.whatsapp.models import SendTextRequest, SendTemplateRequest, SendResponse


def _is_retryable_error(exception):
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (429,) or 500 <= exception.response.status_code < 600
    return isinstance(exception, (httpx.TimeoutException, httpx.ConnectError))


class MetaClient:
    BASE_URL = "https://graph.facebook.com/v20.0"

    def __init__(self, tenant_config: TenantConfig):
        self.phone_number_id = tenant_config.phone_number_id
        self.access_token = tenant_config.access_token
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(5.0, connect=3.0),
        )

    async def close(self):
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(2),
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def send_message(self, payload: SendTextRequest | SendTemplateRequest) -> SendResponse:
        url = f"/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        data = payload.model_dump(exclude_none=True)
        response = await self._client.post(url, headers=headers, json=data)
        response.raise_for_status()
        return SendResponse.model_validate(response.json())
