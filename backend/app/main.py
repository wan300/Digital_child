from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.router import api_router
from app.core.config import get_settings
from app.db.init_db import create_db_and_tables, ensure_admin_user
from app.db.session import AsyncSessionLocal


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_db_and_tables()
    async with AsyncSessionLocal() as session:
        assert isinstance(session, AsyncSession)
        await ensure_admin_user(session)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.project_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def root() -> str:
        frontend_url = "http://127.0.0.1:5173/"
        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{settings.project_name}</title>
    <style>
      body {{
        margin: 0;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f4f7f6;
        color: #17201f;
      }}
      main {{
        max-width: 720px;
        margin: 72px auto;
        padding: 32px;
        background: white;
        border: 1px solid #d8e1df;
        border-radius: 8px;
      }}
      h1 {{ margin: 0 0 12px; font-size: 28px; }}
      p {{ color: #536966; line-height: 1.6; }}
      nav {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }}
      a {{
        display: inline-block;
        padding: 10px 14px;
        border-radius: 6px;
        border: 1px solid #2f6f63;
        color: #0f4f44;
        text-decoration: none;
        font-weight: 600;
      }}
      a.primary {{ background: #2f6f63; color: white; }}
    </style>
  </head>
  <body>
    <main>
      <h1>{settings.project_name} API</h1>
      <p>The backend is running. Use the frontend app for the observer console, or open the API docs for backend routes.</p>
      <nav>
        <a class="primary" href="{frontend_url}">Open frontend</a>
        <a href="/docs">API docs</a>
        <a href="{settings.api_prefix}/health">Health</a>
      </nav>
    </main>
  </body>
</html>"""
    return app


app = create_app()
