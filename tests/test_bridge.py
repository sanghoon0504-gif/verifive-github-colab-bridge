import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app import app


class FakeColabHandler(BaseHTTPRequestHandler):
    """Small local stand-in for the Colab server; no model or GPU is used."""

    def log_message(self, format, *args):
        pass

    def send_payload(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            if self.headers.get("ngrok-skip-browser-warning") != "1":
                self.send_payload(409, "text/plain; charset=utf-8", b"warning not bypassed")
                return
            html = "<!doctype html><title>VeriFive test UI</title>"
            self.send_payload(200, "text/html; charset=utf-8", html.encode())
            return
        if self.path.startswith("/api/eval/csv/"):
            self.send_payload(200, "text/csv; charset=utf-8", "질문,결과\n테스트,통과\n".encode())
            return

        body = json.dumps({
            "path": self.path,
            "skip_warning": self.headers.get("ngrok-skip-browser-warning"),
            "cookie": self.headers.get("cookie"),
            "authorization": self.headers.get("authorization"),
            "x_github_token": self.headers.get("x-github-token"),
        }).encode()
        self.send_payload(200, "application/json", body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(length).decode()
        body = json.dumps({
            "path": self.path,
            "request_body": request_body,
            "skip_warning": self.headers.get("ngrok-skip-browser-warning"),
            "cookie": self.headers.get("cookie"),
            "authorization": self.headers.get("authorization"),
            "x_github_token": self.headers.get("x-github-token"),
        }).encode()
        self.send_payload(200, "application/json", body)


@pytest.fixture()
def fake_colab():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeColabHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["ALLOW_LOCAL_HTTP"] = "1"
    os.environ["COLAB_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
    yield
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()
    os.environ.pop("COLAB_BASE_URL", None)
    os.environ.pop("ALLOW_LOCAL_HTTP", None)


async def bridge_request(method, path, **kwargs):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as client:
            return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_html_and_ngrok_warning_bypass(fake_colab):
    response = await bridge_request("GET", "/")
    assert response.status_code == 200
    assert "VeriFive test UI" in response.text


@pytest.mark.asyncio
async def test_ask_body_query_and_private_headers(fake_colab):
    response = await bridge_request(
        "POST",
        "/api/ask?demo=1",
        json={"question": "테스트 질문"},
        headers={
            "Cookie": "github-session=must-not-leak",
            "Authorization": "Bearer must-not-leak",
            "X-Github-Token": "must-not-leak",
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["path"] == "/api/ask?demo=1"
    assert json.loads(payload["request_body"]) == {"question": "테스트 질문"}
    assert payload["skip_warning"] == "1"
    assert payload["cookie"] is None
    assert payload["authorization"] is None
    assert payload["x_github_token"] is None


@pytest.mark.asyncio
async def test_status_and_csv_routes(fake_colab):
    status = await bridge_request("GET", "/api/ask/status/test-job")
    assert status.status_code == 200
    assert status.json()["path"] == "/api/ask/status/test-job"

    csv_file = await bridge_request("GET", "/api/eval/csv/test-job")
    assert csv_file.status_code == 200
    assert csv_file.headers["content-type"].startswith("text/csv")
    assert "테스트,통과" in csv_file.text


@pytest.mark.asyncio
async def test_health_and_missing_configuration():
    os.environ.pop("COLAB_BASE_URL", None)
    health = await bridge_request("GET", "/bridge/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "colab_configured": False}

    root = await bridge_request("GET", "/")
    assert root.status_code == 503
    assert "COLAB_BASE_URL" in root.json()["detail"]
