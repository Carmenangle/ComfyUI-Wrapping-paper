import sqlite3
from collections.abc import Iterator

from app.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def connection_scope() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            create table if not exists ai_providers (
                id text primary key,
                name text not null,
                provider_type text not null,
                base_url text not null,
                api_key text not null default '',
                default_model text not null default '',
                supports_model_discovery integer not null default 1,
                enabled integer not null default 1,
                created_at text not null,
                updated_at text not null
            );

            create table if not exists ai_provider_models (
                id text primary key,
                provider_id text not null,
                model_name text not null,
                source text not null,
                supports_image integer,
                created_at text not null,
                unique(provider_id, model_name),
                foreign key(provider_id) references ai_providers(id) on delete cascade
            );
            """
        )