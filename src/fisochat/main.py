"""Run the QQ recorder and terminal-support HTTP service."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from dotenv import load_dotenv

from .config import AppConfig
from .interfaces.qq.client import ChatRecorderClient


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
    parser = argparse.ArgumentParser(description="QQ 群消息记录与终端后台服务")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="环境变量文件，默认当前目录 .env")
    parser.add_argument("--check-config", action="store_true", help="检查配置后退出，不连接 QQ")
    args = parser.parse_args(argv)
    load_dotenv(args.env_file)
    try:
        config = AppConfig.from_env()
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
        asyncio.run(run_recorder(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
