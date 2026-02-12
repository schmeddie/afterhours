"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the After Hours platform."""

    # Parliament API
    parliament_api_base_url: str = "https://members-api.parliament.uk/api"

    # Companies House API
    companies_house_api_key: str = ""
    companies_house_stream_key: str = ""

    # Google Gemini
    gemini_api_key: str = ""

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # DuckDB
    duckdb_path: str = "data/afterhours.duckdb"

    # Compliance thresholds
    risk_score_review_threshold: int = 70
    auto_approve_below: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
