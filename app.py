"""GitHub Codespaces -> Colab/ngrok reverse proxy for the VeriFive demo."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
PRIVATE_REQUEST_HEADERS = {
    "authorization",
    "cookie",
    "x-github-token",
}
REQUEST_TIMEOUT_SECONDS = 600


def get_colab_base_url() -> str:
    """Read and validate the fixed upstream URL; users cannot choose it per request."""
    base_url = os.environ.get("COLAB_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=503,
            detail="COLAB_BASE_URL에 현재 Colab의 ngrok 주소를 설정하세요.",
        )

    parsed = urlsplit(base_url)
    is_local_test = (
        os.environ.get("ALLOW_LOCAL_HTTP") == "1"
        and parsed.hostname in {"127.0.0.1", "localhost"}
    )
    if (parsed.scheme != "https" and not is_local_test) or not parsed.netloc:
        raise HTTPException(
            status_code=500,
            detail="COLAB_BASE_URL은 https://로 시작하는 ngrok 주소여야 합니다.",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=500,
            detail="COLAB_BASE_URL에 계정 정보, 쿼리, 프래그먼트를 넣지 마세요.",
        )
    return base_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=15)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="VeriFive GitHub-Colab Bridge",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/bridge/health")
async def bridge_health():
    """Check the bridge configuration without starting a model request."""
    try:
        get_colab_base_url()
        configured = True
    except HTTPException:
        configured = False
    return {"status": "ok", "colab_configured": configured}


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(request: Request, path: str):
    base_url = get_colab_base_url()
    target_url = f"{base_url}{request.url.path}"
    query = request.url.query or None

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
        and key.lower() not in PRIVATE_REQUEST_HEADERS
        and key.lower() not in {"host", "content-length"}
    }
    headers["ngrok-skip-browser-warning"] = "1"
    headers["user-agent"] = "VeriFive-GitHub-Bridge/1.0"

    try:
        upstream = await request.app.state.http_client.request(
            method=request.method,
            url=target_url,
            params=query,
            content=await request.body(),
            headers=headers,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Colab 응답 시간이 초과됐습니다. 서버 상태를 확인하세요.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Colab에 연결하지 못했습니다. ngrok 주소와 실행 상태를 확인하세요.",
        ) from exc

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
        and key.lower() not in {"content-length", "content-encoding"}
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
