"""FastAPI application serving the After Hours Political Graph API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from afterhours.api.routes import graph, compliance, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialise and tear down shared resources."""
    # Startup – import here to avoid circular deps at module level
    from afterhours.config.database import get_duckdb_connection

    conn = get_duckdb_connection()
    app.state.duckdb = conn
    yield
    # Shutdown
    conn.close()


app = FastAPI(
    title="After Hours",
    description="UK Political Transparency API – linking Parliament, Companies House, and Local Council data.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(graph.router, prefix="/api/v1/graph", tags=["Graph"])
app.include_router(compliance.router, prefix="/api/v1/compliance", tags=["Compliance"])
