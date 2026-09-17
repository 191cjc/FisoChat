"""Small standalone configuration, with aliases for migrated AiQQ settings."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


ALIASES = {
    "FISOCHAT_DB": "AIQQ_GROUP_MESSAGE_DB",
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
    admin_token: str = field(repr=False)
    sticker_directory: Path
    sticker_public_base_url: str
    sticker_signing_secret: str = field(repr=False)
    web_host: str = "127.0.0.1"
    web_port: int = 8789
    http_timeout_seconds: int = 30
    gateway_restart_timeout_seconds: int = 90
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> AppConfig:
        values = os.environ if values is None else values
        required = [
            "QQ_BOT_APPID",
            "QQ_BOT_SECRET",
            "FISOCHAT_ADMIN_TOKEN",
            "FISOCHAT_STICKER_PUBLIC_BASE_URL",
            "FISOCHAT_STICKER_SIGNING_SECRET",
        ]
        admin_token = load_admin_token(values)
        for name in required:
            configured = admin_token if name == "FISOCHAT_ADMIN_TOKEN" else value(values, name)
            if not configured:
                raise ValueError(f"请配置 {name}。")
        database_path = value(values, "FISOCHAT_DB", "data/group_messages.db")
        if not database_path:
            raise ValueError("FISOCHAT_DB 不能为空。")
        host = value(values, "FISOCHAT_WEB_HOST", "127.0.0.1")
        if not host:
            raise ValueError("FISOCHAT_WEB_HOST 不能为空。")
        level = value(values, "FISOCHAT_LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("FISOCHAT_LOG_LEVEL 无效。")
        sticker_directory = value(values, "FISOCHAT_STICKER_DIR", "data/stickers")
        if not sticker_directory:
            raise ValueError("FISOCHAT_STICKER_DIR 不能为空。")
        public_base_url = _public_base_url(
            value(values, "FISOCHAT_STICKER_PUBLIC_BASE_URL")
        )
        signing_secret = value(values, "FISOCHAT_STICKER_SIGNING_SECRET")
        if len(signing_secret.encode("utf-8")) < 32:
            raise ValueError("FISOCHAT_STICKER_SIGNING_SECRET 至少需要 32 字节。")
        return cls(
            app_id=value(values, "QQ_BOT_APPID"),
            secret=value(values, "QQ_BOT_SECRET"),
            database_path=Path(database_path).expanduser(),
            admin_token=admin_token,
            sticker_directory=Path(sticker_directory).expanduser(),
            sticker_public_base_url=public_base_url,
            sticker_signing_secret=signing_secret,
            web_host=host,
            web_port=integer(values, "FISOCHAT_WEB_PORT", 8789, 1, 65535),
            http_timeout_seconds=integer(values, "FISOCHAT_HTTP_TIMEOUT_SECONDS", 30, 5, 120),
            gateway_restart_timeout_seconds=integer(
                values, "FISOCHAT_GATEWAY_RESTART_TIMEOUT_SECONDS", 90, 10, 3600
            ),
            log_level=level,
        )


def _public_base_url(raw: str) -> str:
    try:
        parsed = urlsplit(raw)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if (
            parsed.scheme != "https"
            or not hostname
            or hostname == "localhost"
            or hostname.endswith(".localhost")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
            or any(ord(char) < 33 or ord(char) == 127 for char in raw)
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if not address.is_global or address.is_multicast:
                raise ValueError
    except ValueError:
        raise ValueError(
            "FISOCHAT_STICKER_PUBLIC_BASE_URL 必须是不含凭据、查询或片段的 HTTPS 地址。"
        ) from None
    return raw.rstrip("/")
