import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_root_serves_backend_landing_page() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "Open frontend" in response.text
    assert "/docs" in response.text
    assert "/api/health" in response.text
