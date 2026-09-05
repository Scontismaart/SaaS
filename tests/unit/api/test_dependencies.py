import types
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException, Request

from src.api.dependencies import (
    get_repo,
    get_pool,
    get_booking_service,
    get_orchestrator,
    get_current_org_id,
)


def _build_request(state_attrs: dict) -> Request:
    req = MagicMock(spec=Request)
    state = types.SimpleNamespace()
    for k, v in state_attrs.items():
        setattr(state, k, v)
    req.app = types.SimpleNamespace(state=state)
    return req


def test_get_repo_success():
    mock_repo = MagicMock()
    req = _build_request({"repo": mock_repo})
    assert get_repo(req) is mock_repo


def test_get_repo_missing_raises_500():
    req = _build_request({})
    with pytest.raises(HTTPException) as exc_info:
        get_repo(req)
    assert exc_info.value.status_code == 500


def test_get_pool_success():
    mock_pool = MagicMock()
    req = _build_request({"pool": mock_pool})
    assert get_pool(req) is mock_pool


def test_get_pool_missing_raises_503():
    req = _build_request({})
    with pytest.raises(HTTPException) as exc_info:
        get_pool(req)
    assert exc_info.value.status_code == 503


def test_get_booking_service_success():
    mock_svc = MagicMock()
    req = _build_request({"booking_service": mock_svc})
    assert get_booking_service(req) is mock_svc


def test_get_booking_service_missing_raises_503():
    req = _build_request({})
    with pytest.raises(HTTPException) as exc_info:
        get_booking_service(req)
    assert exc_info.value.status_code == 503


def test_get_orchestrator_from_state():
    mock_orch = MagicMock()
    req = _build_request({"orchestrator": mock_orch})
    assert get_orchestrator(req) is mock_orch


def test_get_current_org_id():
    user = {"organization_id": "org-123", "role": "owner"}
    assert get_current_org_id(user) == "org-123"


def test_get_current_org_id_missing_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        get_current_org_id({"role": "owner"})
    assert exc_info.value.status_code == 401
