#!/usr/bin/env python3
"""Send one proactive group message or contextual reply through FisoChat."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .config import integer, load_admin_token


EXIT_ARGUMENT = 2
EXIT_UNAVAILABLE = 3
EXIT_REJECTED = 4
EXIT_UNKNOWN = 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one proactive QQ group message."
    )
    parser.add_argument("--group", required=True, help="Target group OpenID.")
    parser.add_argument(
        "--reply-to",
        help="Reply to a specific @ message from the last five minutes.",
    )
    parser.add_argument("--text", help="Message text; omit to read standard input.")
    parser.add_argument("--endpoint", help="本机管理接口地址，默认使用 FISOCHAT_WEB_PORT。")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)
    if args.endpoint is None:
        try:
            port = integer(os.environ, "FISOCHAT_WEB_PORT", 8789, 1, 65535)
        except ValueError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return EXIT_ARGUMENT
        args.endpoint = f"http://127.0.0.1:{port}/internal/group-messages"
    try:
        endpoint = urlsplit(args.endpoint)
        valid_endpoint = (
            endpoint.scheme == "http"
            and endpoint.hostname in {"127.0.0.1", "::1"}
            and endpoint.username is None
            and endpoint.password is None
            and (endpoint.port is None or 1 <= endpoint.port <= 65535)
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        print("错误：管理接口必须使用本机 HTTP 地址。", file=sys.stderr)
        return EXIT_ARGUMENT
    content = args.text if args.text is not None else sys.stdin.read()
    if not content.strip() or len(content) > 2000:
        print("错误：消息正文必须包含 1 至 2000 个字符。", file=sys.stderr)
        return EXIT_ARGUMENT
    try:
        token = load_admin_token()
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_ARGUMENT
    if not token:
        print("错误：未配置 FISOCHAT_ADMIN_TOKEN 或 Token 文件。", file=sys.stderr)
        return EXIT_ARGUMENT
    payload = {"group_openid": args.group, "content": content.strip()}
    if args.reply_to:
        payload["reply_to_message_id"] = args.reply_to
    request = Request(
        args.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=130) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
            message = result["error"]["message"]
        except Exception:
            message = f"HTTP {exc.code}"
        print(f"发送失败：{message}", file=sys.stderr)
        return EXIT_REJECTED
    except URLError as exc:
        print(f"机器人管理接口不可用：{exc.reason}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except Exception as exc:
        print(f"未知错误：{type(exc).__name__}", file=sys.stderr)
        return EXIT_UNKNOWN
    print(f"发送成功：message_id={result['message_id']} sent_at={result['sent_at']}")
    if not result.get("recorded", True):
        print("注意：QQ 已确认发送，但本地记录失败，请检查数据库；不要重复发送。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
