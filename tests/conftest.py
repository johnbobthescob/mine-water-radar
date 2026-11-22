"""Make accidental network access fail for every pytest test."""

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Block socket connects and DNS resolution; tests must inject fake transports."""

    def blocked(*args, **kwargs):
        raise RuntimeError("network access is blocked during tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "gethostbyname", blocked)
    monkeypatch.setattr(socket, "gethostbyname_ex", blocked)
    monkeypatch.setattr(socket, "gethostbyaddr", blocked)

