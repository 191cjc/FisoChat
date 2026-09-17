"""Run the recorder, or a standalone read-only viewer without QQ credentials."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

from .config import AppConfig
from .database import GroupMessageRepository, SQLiteConnection
from .interfaces.qq.client import ChatRecorderClient
from .interfaces.qq.gateway import GatewayStatus
from .interfaces.web.app import create_web_application


class ReadOnlySender:
    async def send_proactive_text(self, **_kwargs: object) -> None:
        raise RuntimeError("只读模式不能发送 QQ 消息。")


def create_read_only_application(config: AppConfig) -> web.Application:
    repository = GroupMessageRepository(SQLiteConnection(config.database_path))
    application = create_web_application(
        config, repository, ReadOnlySender(), GatewayStatus(), web_only=True
    )

    async def database_lifecycle(_application: web.Application):
        try:
            await repository.initialize()
            yield
        finally:
            await repository.close()

    application.cleanup_ctx.append(database_lifecycle)
    return application


async def run_recorder(config: AppConfig) -> None:
    current_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    if current_task is not None:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, current_task.cancel)
    try:
        async with ChatRecorderClient(config) as client:
            await client.start(config.app_id, config.secret)
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QQ 群消息记录、查看和发送服务")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="环境变量文件，默认当前目录 .env")
    parser.add_argument("--web-only", action="store_true", help="只运行查看页，不连接 QQ，不发送消息")
    parser.add_argument("--check-config", action="store_true", help="检查配置后退出，不连接 QQ")
    args = parser.parse_args(argv)
    load_dotenv(args.env_file)
    try:
        config = AppConfig.from_env(web_only=args.web_only)
    except ValueError as exc:
        parser.error(str(exc))
    if args.check_config:
        print("配置检查通过。")
        return 0
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    )
    try:
        if args.web_only:
            web.run_app(
                create_read_only_application(config),
                host=config.web_host,
                port=config.web_port,
                access_log=None,
            )
        else:
            asyncio.run(run_recorder(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
