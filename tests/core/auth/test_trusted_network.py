import os
from fastapi import Request
import pytest
from src.core.auth.trusted_network import get_client_ip, is_ip_in_allowed_cidrs

def test_get_client_ip_with_x_forwarded_for(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.18.0.2/32")
    # Simulate attacker sending X-Forwarded-For: 127.0.0.1
    # Traefik appends the real IP (e.g. 203.0.113.1)
    class DummyClient:
        host = "172.18.0.2" # Traefik internal IP
    
    class DummyRequest:
        client = DummyClient()
        headers = {
            "x-forwarded-for": "127.0.0.1, 203.0.113.1"
        }
    
    ip = get_client_ip(DummyRequest())
    assert str(ip) == "203.0.113.1", "Should extract the rightmost IP appended by Traefik, ignoring spoofed client IP"

def test_get_client_ip_without_x_forwarded_for():
    class DummyClient:
        host = "192.168.1.10"
    
    class DummyRequest:
        client = DummyClient()
        headers = {}
    
    ip = get_client_ip(DummyRequest())
    assert str(ip) == "192.168.1.10"

def test_is_ip_in_allowed_cidrs(monkeypatch):
    monkeypatch.setenv("TEST_ALLOWED_CIDRS", "10.0.0.0/8,192.168.0.0/16")
    
    import ipaddress
    
    assert is_ip_in_allowed_cidrs(ipaddress.ip_address("10.5.5.5"), "TEST_ALLOWED_CIDRS", ()) == True
    assert is_ip_in_allowed_cidrs(ipaddress.ip_address("192.168.1.100"), "TEST_ALLOWED_CIDRS", ()) == True
    assert is_ip_in_allowed_cidrs(ipaddress.ip_address("203.0.113.1"), "TEST_ALLOWED_CIDRS", ()) == False

def test_spoofed_request_is_rejected(monkeypatch):
    monkeypatch.setenv("TEST_ALLOWED_CIDRS", "127.0.0.0/8")
    
    class DummyClient:
        host = "172.18.0.2"
    
    class DummyRequest:
        client = DummyClient()
        headers = {
            "x-forwarded-for": "127.0.0.1, 203.0.113.1"
        }
    
    ip = get_client_ip(DummyRequest())
    assert is_ip_in_allowed_cidrs(ip, "TEST_ALLOWED_CIDRS", ()) == False


def _request(peer, xff):
    from types import SimpleNamespace
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": xff})


def test_untrusted_peer_cannot_spoof_private_ip(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert str(get_client_ip(_request("203.0.113.5", "127.0.0.1"))) == "203.0.113.5"


def test_trusted_chain_stops_at_first_untrusted_hop(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.18.0.2/32,10.1.1.1/32")
    assert str(get_client_ip(_request("172.18.0.2", "127.0.0.1,203.0.113.5,10.1.1.1"))) == "203.0.113.5"


@pytest.mark.parametrize("xff", ["bad-ip", "203.0.113.5,", ",".join(["10.1.1.1"] * 33)])
def test_malformed_proxy_chain_fails_closed(monkeypatch, xff):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.18.0.2/32")
    assert get_client_ip(_request("172.18.0.2", xff)) is None


def test_invalid_proxy_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "not-a-network")
    assert get_client_ip(_request("172.18.0.2", "127.0.0.1")) is None
