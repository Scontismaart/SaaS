import os
from fastapi import Request
import pytest
from src.core.auth.trusted_network import get_client_ip, is_ip_in_allowed_cidrs

def test_get_client_ip_with_x_forwarded_for():
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
