"""Default to the interactive console; retain explicit server and send modes."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "serve":
        from .main import main as serve
        return serve(arguments[1:])
    if arguments and arguments[0] == "send":
        from .send import main as send
        return send(arguments[1:])
    if "--web-only" in arguments or "--check-config" in arguments:
        from .main import main as serve
        return serve(arguments)
    if arguments and arguments[0] in {"-h", "--help"}:
        print("FisoChat · QQ 聊天终端\n\n"
              "  fisochat [--env-file FILE] [--group GROUP_ID]   打开交互终端\n"
              "  fisochat console --help                       终端参数\n"
              "  fisochat serve [--web-only]                   启动后台服务\n"
              "  fisochat send --group GROUP_ID --text TEXT    发送一条消息\n\n"
              "终端需要本机后台服务和 FISOCHAT_ADMIN_TOKEN。")
        return 0
    if arguments and arguments[0] == "console":
        arguments = arguments[1:]
    from .console import main as console
    return console(arguments)
