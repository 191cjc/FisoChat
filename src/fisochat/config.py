"""Small standalone configuration, with aliases for migrated AiQQ settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


ALIASES = {
    "FISOCHAT_DB": "AIQQ_GROUP_MESSAGE_DB",
    "FISOCHAT_VIEW_USERNAME": "AIQQ_GROUP_MESSAGE_VIEW_USERNAME",
    "FISOCHAT_VIEW_PASSWORD": "AIQQ_GROUP_MESSAGE_VIEW_PASSWORD",
    "FISOCHAT_WEB_HOST": "AIQQ_HEALTH_HOST",
    "FISOCHAT_WEB_PORT": "AIQQ_HEALTH_PORT",
    "FISOCHAT_ADMIN_TOKEN": "AIQQ_ADMIN_TOKEN",
    "FISOCHAT_ADMIN_TOKEN_FILE": "AIQQ_ADMIN_TOKEN_FILE",
    "FISOCHAT_HTTP_TIMEOUT_SECONDS": "AIQQ_QQ_HTTP_TIMEOUT_SECONDS",
    "FISOCHAT_GATEWAY_RESTART_TIMEOUT_SECONDS": "AIQQ_GATEWAY_RESTART_TIMEOUT_SECONDS",
}


def value(values: Mapping[str, str], name: str, default: str = "") -> str:
    if name in values:
        return values[name].strip()
    return values.get(ALIASES.get(name, name), default).strip()


def integer(values: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    try:
        result = int(value(values, name, str(default)))
    except ValueError:
        raise ValueError(f"{name} 必须是整数。") from None
    if not low <= result <= high:
        raise ValueError(f"{name} 必须在 {low} 至 {high} 之间。")
    return result


def load_admin_token(values: Mapping[str, str] | None = None) -> str:
    values = os.environ if values is None else values
    token = value(values, "FISOCHAT_ADMIN_TOKEN")
    if token:
        return token
    filename = value(values, "FISOCHAT_ADMIN_TOKEN_FILE")
    if not filename:
        return ""
    path = Path(filename).expanduser()
    try:
        if path.stat().st_mode & 0o077:
            raise ValueError("FISOCHAT_ADMIN_TOKEN_FILE 权限必须为 0600。")
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise ValueError("无法读取 FISOCHAT_ADMIN_TOKEN_FILE。") from None
    if not token:
        raise ValueError("FISOCHAT_ADMIN_TOKEN_FILE 不能为空。")
    return token


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    secret: str = field(repr=False)
    database_path: Path
    view_username: str
    view_password: str = field(repr=False)
    admin_token: str = field(repr=False)
    web_host: str = "127.0.0.1"
    web_port: int = 8789
    http_timeout_seconds: int = 30
    gateway_restart_timeout_seconds: int = 90
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls, values: Mapping[str, str] | None = None, *, web_only: bool = False
    ) -> AppConfig:
        values = os.environ if values is None else values
        required = ["FISOCHAT_VIEW_USERNAME", "FISOCHAT_VIEW_PASSWORD"]
        if not web_only:
            required += ["QQ_BOT_APPID", "QQ_BOT_SECRET"]
        for name in required:
            if not value(values, name, "admin" if name == "FISOCHAT_VIEW_USERNAME" else ""):
                raise ValueError(f"请配置 {name}。")
        username = value(values, "FISOCHAT_VIEW_USERNAME", "admin")
        if ":" in username:
            raise ValueError("FISOCHAT_VIEW_USERNAME 不能包含冒号。")
        database_path = value(values, "FISOCHAT_DB", "data/group_messages.db")
        if not database_path:
            raise ValueError("FISOCHAT_DB 不能为空。")
        host = value(values, "FISOCHAT_WEB_HOST", "127.0.0.1")
        if not host:
            raise ValueError("FISOCHAT_WEB_HOST 不能为空。")
        level = value(values, "FISOCHAT_LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("FISOCHAT_LOG_LEVEL 无效。")
        return cls(
            app_id=value(values, "QQ_BOT_APPID"),
            secret=value(values, "QQ_BOT_SECRET"),
            database_path=Path(database_path).expanduser(),
            view_username=username,
            view_password=value(values, "FISOCHAT_VIEW_PASSWORD"),
            admin_token=load_admin_token(values),
            web_host=host,
            web_port=integer(values, "FISOCHAT_WEB_PORT", 8789, 1, 65535),
            http_timeout_seconds=integer(values, "FISOCHAT_HTTP_TIMEOUT_SECONDS", 30, 5, 120),
            gateway_restart_timeout_seconds=integer(
                values, "FISOCHAT_GATEWAY_RESTART_TIMEOUT_SECONDS", 90, 10, 3600
            ),
            log_level=level,
        )
