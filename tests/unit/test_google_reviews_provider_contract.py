from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, MagicMock

import httplib2
import pytest
from googleapiclient.discovery import build_from_document

from src.core.reviews.google_service import GoogleBusinessService


DISCOVERY_DOCUMENT = json.dumps({
    "kind": "discovery#restDescription",
    "discoveryVersion": "v1",
    "id": "mybusiness:v4",
    "name": "mybusiness",
    "version": "v4",
    "revision": "test-contract",
    "rootUrl": "https://mybusiness.googleapis.com/",
    "servicePath": "",
    "baseUrl": "https://mybusiness.googleapis.com/",
    "batchPath": "batch",
    "resources": {
        "accounts": {
            "resources": {
                "locations": {
                    "resources": {
                        "reviews": {
                            "methods": {
                                "list": {
                                    "id": "mybusiness.accounts.locations.reviews.list",
                                    "path": "v4/{+parent}/reviews",
                                    "httpMethod": "GET",
                                    "parameters": {
                                        "parent": {
                                            "type": "string",
                                            "required": True,
                                            "location": "path",
                                            "pattern": "^accounts/[^/]+/locations/[^/]+$",
                                        },
                                        "pageSize": {
                                            "type": "integer",
                                            "location": "query",
                                        },
                                        "pageToken": {
                                            "type": "string",
                                            "location": "query",
                                        },
                                    },
                                    "response": {"$ref": "ListReviewsResponse"},
                                }
                            }
                        }
                    }
                }
            }
        }
    },
    "schemas": {
        "ListReviewsResponse": {
            "type": "object",
            "properties": {
                "reviews": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"reviewId": {"type": "string"}},
                    },
                },
                "nextPageToken": {"type": "string"},
            },
        }
    },
})


class RecordingHttp:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.calls.append({"uri": uri, "method": method})
        response = httplib2.Response({"status": "200", "content-type": "application/json"})
        return response, json.dumps(self.payload).encode("utf-8")


def _generated_service(http):
    return build_from_document(DISCOVERY_DOCUMENT, http=http)


@pytest.mark.parametrize(
    ("location_name", "expected_parent"),
    [
        ("locations/LOC-1", "accounts/ACCT_1/locations/LOC-1"),
        (
            "accounts/ACCT_1/locations/LOC-1",
            "accounts/ACCT_1/locations/LOC-1",
        ),
    ],
)
@pytest.mark.asyncio
async def test_reviews_list_uses_generated_google_contract_and_canonical_parent(
    monkeypatch, location_name, expected_parent
):
    monkeypatch.setenv("GOOGLE_BUSINESS_ENABLED", "true")
    http = RecordingHttp({"reviews": [{"reviewId": "review-1"}]})
    generated_service = _generated_service(http)
    reviews_service = GoogleBusinessService(MagicMock(), "Y2xvbmUtZmVybmV0LWtleS0zMi1ieXRlcy1sb25nISE=")

    reviews = await reviews_service._list_reviews(
        generated_service,
        "accounts/ACCT_1",
        location_name,
        page_size=2,
    )

    assert reviews == [{"reviewId": "review-1"}]
    assert len(http.calls) == 1
    request = http.calls[0]
    assert request["method"] == "GET"
    parsed = urlsplit(request["uri"])
    assert parsed.path == "/v4/accounts/ACCT_1/locations/LOC-1/reviews"
    assert parse_qs(parsed.query) == {"pageSize": ["2"], "alt": ["json"]}
    assert expected_parent == "accounts/ACCT_1/locations/LOC-1"


@pytest.mark.parametrize(
    ("account_name", "location_name"),
    [
        ("ACCT_1", "locations/LOC-1"),
        ("accounts/ACCT_1", "LOC-1"),
        ("accounts/ACCT_1", "accounts/OTHER/locations/LOC-1"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_cross_account_location_is_denied_before_http(
    monkeypatch, account_name, location_name
):
    monkeypatch.setenv("GOOGLE_BUSINESS_ENABLED", "true")
    http = RecordingHttp({"reviews": []})
    generated_service = _generated_service(http)
    reviews_service = GoogleBusinessService(MagicMock(), "Y2xvbmUtZmVybmV0LWtleS0zMi1ieXRlcy1sb25nISE=")

    with pytest.raises(ValueError):
        await reviews_service._list_reviews(
            generated_service, account_name, location_name
        )
    assert http.calls == []


@pytest.mark.asyncio
async def test_build_service_uses_explicit_official_discovery_document(monkeypatch):
    import src.core.reviews.google_service as module

    monkeypatch.setenv("GOOGLE_BUSINESS_ENABLED", "true")
    service = GoogleBusinessService(MagicMock(), "Y2xvbmUtZmVybmV0LWtleS0zMi1ieXRlcy1sb25nISE=")
    service._get_credentials = AsyncMock(return_value=object())
    generated = object()
    build = MagicMock(return_value=generated)
    to_thread = AsyncMock(return_value=generated)
    monkeypatch.setattr(module, "build", build)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)

    assert await service._build_service("org-test") is generated
    args, kwargs = to_thread.await_args
    assert args[:3] == (build, "mybusiness", "v4")
    assert kwargs["static_discovery"] is False
    assert kwargs["discoveryServiceUrl"] == (
        "https://mybusiness.googleapis.com/$discovery/rest?version=v4"
    )
