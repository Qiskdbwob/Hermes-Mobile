import asyncio
import json
from pathlib import Path

import httpx
import pytest

from hermes_mobile.remote import (
    RemoteAuthenticationError,
    RemoteConnectionError,
    RemoteHermesClient,
    RemoteSecretStore,
    build_gateway_ws_url,
    insecure_transport_is_private,
    normalize_remote_base_url,
    redact_transport_error,
)


class FakeWebSocket:
    def __init__(self, handler=None):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.handler = handler
        self.incoming.put_nowait(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {"type": "gateway.ready", "payload": {"skin": "nous"}},
                }
            )
        )

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.incoming.get()
        if item is StopAsyncIteration:
            raise StopAsyncIteration
        return item

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        if self.handler:
            response = self.handler(frame)
            if response is not None:
                self.incoming.put_nowait(json.dumps(response))

    async def close(self):
        if not self.closed:
            self.closed = True
            self.incoming.put_nowait(StopAsyncIteration)


class SocketFactory:
    def __init__(self, ws):
        self.ws = ws
        self.urls = []
        self.kwargs = []

    async def __call__(self, url, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        return self.ws


def status_body(**overrides):
    body = {
        "version": "0.19.1",
        "auth_required": False,
        "auth_providers": [],
        "overall": "ok",
        "profiles": ["default"],
        "gateway_running": True,
    }
    body.update(overrides)
    return body


def test_transport_errors_redact_all_credentials():
    text = redact_transport_error(
        "wss://host/api/ws?ticket=one-time&token=query-token "
        "Authorization: Bearer header-token password-value raw-token",
        "password-value",
        "raw-token",
    )
    assert "one-time" not in text
    assert "query-token" not in text
    assert "header-token" not in text
    assert "password-value" not in text
    assert "raw-token" not in text
    assert text.count("<redacted>") >= 5


def test_normalize_remote_base_url_preserves_prefix_and_rejects_credentials():
    assert (
        normalize_remote_base_url(" https://example.com/hermes/// ") == "https://example.com/hermes"
    )
    assert normalize_remote_base_url("http://[::1]:9119/") == "http://[::1]:9119"
    with pytest.raises(ValueError, match="Credentials"):
        normalize_remote_base_url("https://user:secret@example.com")
    with pytest.raises(ValueError, match="query"):
        normalize_remote_base_url("https://example.com?token=secret")
    with pytest.raises(ValueError, match="http"):
        normalize_remote_base_url("ftp://example.com")


def test_ws_url_matches_desktop_contract():
    assert (
        build_gateway_ws_url("https://host/hermes", ticket="a b")
        == "wss://host/hermes/api/ws?ticket=a%20b"
    )
    assert (
        build_gateway_ws_url("http://127.0.0.1:9119", token="a/b")
        == "ws://127.0.0.1:9119/api/ws?token=a%2Fb"
    )


def test_insecure_transport_policy_allows_private_and_blocks_public():
    assert insecure_transport_is_private("http://127.0.0.1:9119")
    assert insecure_transport_is_private("http://100.98.210.62:9119")
    assert insecure_transport_is_private("http://192.168.1.3:9119")
    assert not insecure_transport_is_private("http://example.com:9119")
    assert insecure_transport_is_private("https://example.com")


@pytest.mark.asyncio
async def test_connect_token_mode_and_rpc_session_create():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=status_body()))
    http = httpx.AsyncClient(transport=transport)

    def handle(frame):
        if frame["method"] == "session.create":
            return {
                "jsonrpc": "2.0",
                "id": frame["id"],
                "result": {"session_id": "live-1", "stored_session_id": "stored-1"},
            }
        return {"jsonrpc": "2.0", "id": frame["id"], "result": {}}

    ws = FakeWebSocket(handle)
    factory = SocketFactory(ws)
    client = RemoteHermesClient(
        "http://127.0.0.1:9119",
        auth_mode="token",
        token="secret",
        http_client=http,
        websocket_factory=factory,
    )
    status = await client.connect()
    created = await client.create_session()

    assert status.version == "0.19.1"
    assert factory.urls == ["ws://127.0.0.1:9119/api/ws?token=secret"]
    assert created["session_id"] == "live-1"
    assert client.session_id == "live-1"
    assert ws.sent[0]["params"]["source"] == "mobile"
    await client.close()
    await http.aclose()


@pytest.mark.asyncio
async def test_basic_auth_uses_cookie_then_single_use_ticket():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/api/status"):
            return httpx.Response(
                200,
                json=status_body(auth_required=True, auth_providers=["basic"]),
            )
        if request.url.path.endswith("/auth/password-login"):
            body = json.loads(request.content)
            assert body == {
                "provider": "basic",
                "username": "joao",
                "password": "not-logged",
                "next": "/",
            }
            return httpx.Response(
                200,
                json={"next": "/"},
                headers={"set-cookie": "hermes_session_at=session; Path=/; HttpOnly"},
            )
        if request.url.path.endswith("/api/auth/ws-ticket"):
            assert "hermes_session_at=session" in request.headers.get("cookie", "")
            return httpx.Response(200, json={"ticket": "one shot", "ttl_seconds": 30})
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    factory = SocketFactory(FakeWebSocket())
    client = RemoteHermesClient(
        "https://remote.example/hermes",
        auth_mode="basic",
        username="joao",
        password="not-logged",
        http_client=http,
        websocket_factory=factory,
    )
    await client.connect()
    assert factory.urls == ["wss://remote.example/hermes/api/ws?ticket=one%20shot"]
    assert [request.url.path for request in seen] == [
        "/hermes/api/status",
        "/hermes/auth/password-login",
        "/hermes/api/auth/ws-ticket",
    ]
    await client.close()
    await http.aclose()


@pytest.mark.asyncio
async def test_basic_auth_rejection_is_specific():
    def handler(request):
        if request.url.path == "/api/status":
            return httpx.Response(
                200, json=status_body(auth_required=True, auth_providers=["basic"])
            )
        return httpx.Response(401)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RemoteHermesClient(
        "https://remote.example",
        auth_mode="basic",
        username="joao",
        password="wrong",
        http_client=http,
        websocket_factory=SocketFactory(FakeWebSocket()),
    )
    with pytest.raises(RemoteAuthenticationError, match="rejected"):
        await client.connect()
    assert client.state == "error"
    await http.aclose()


@pytest.mark.asyncio
async def test_public_plain_http_is_blocked_before_network():
    client = RemoteHermesClient("http://example.com:9119")
    with pytest.raises(RemoteConnectionError, match="Plain HTTP"):
        await client.connect()
    await client.close()


@pytest.mark.asyncio
async def test_events_and_out_of_order_rpc_responses_are_correlated():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=status_body()))
    http = httpx.AsyncClient(transport=transport)
    events = []
    ws = FakeWebSocket()
    client = RemoteHermesClient(
        "http://localhost:9119",
        http_client=http,
        websocket_factory=SocketFactory(ws),
        on_event=events.append,
    )
    await client.connect()
    first = asyncio.create_task(client.request("first"))
    second = asyncio.create_task(client.request("second"))
    await asyncio.sleep(0)
    ids = {frame["method"]: frame["id"] for frame in ws.sent}
    ws.incoming.put_nowait(
        json.dumps({"jsonrpc": "2.0", "id": ids["second"], "result": {"value": 2}})
    )
    ws.incoming.put_nowait(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": "message.delta",
                    "session_id": "s1",
                    "payload": {"text": "hi"},
                },
            }
        )
    )
    ws.incoming.put_nowait(
        json.dumps({"jsonrpc": "2.0", "id": ids["first"], "result": {"value": 1}})
    )
    assert await first == {"value": 1}
    assert await second == {"value": 2}
    await asyncio.sleep(0)
    assert any(event.type == "message.delta" and event.payload["text"] == "hi" for event in events)
    await client.close()
    await http.aclose()


def test_secret_store_encrypts_and_round_trips(tmp_path: Path):
    store = RemoteSecretStore(tmp_path)
    store.save(password="super-secret", token="token-value")
    assert store.load() == {"password": "super-secret", "token": "token-value"}
    encrypted = (tmp_path / "remote" / "credentials.bin").read_bytes()
    assert b"super-secret" not in encrypted
    assert b"token-value" not in encrypted
    assert (tmp_path / "remote" / ".credential-key").stat().st_mode & 0o077 == 0
    store.save(password="")
    assert store.load() == {"token": "token-value"}
    store.clear()
    assert store.load() == {}
