"""Database connection factories for DuckDB and Neo4j."""

from __future__ import annotations

import duckdb
from neo4j import GraphDatabase

from .settings import settings


def get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection to the configured database path."""
    return duckdb.connect(settings.duckdb_path)


def get_neo4j_driver():
    """Return an authenticated Neo4j driver instance."""
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
