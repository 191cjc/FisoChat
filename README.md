# FisoChat

FisoChat 是一个终端优先的 QQ 群消息工具，使用 Python 3.11+、腾讯官方
`qq-botpy`、aiohttp、SQLite 和 Textual。它接收并保存群消息，在终端中浏览和发送消息，
也可以把收到的 PNG/JPEG 图片收藏到全局表情库后再次发送。

## 功能

- 通过 QQ WebSocket 网关接收 `GROUP_MESSAGE_CREATE` 和
  `GROUP_AT_MESSAGE_CREATE`，按群和消息 ID 去重并保留原始消息数据。
- 运行 `fisochat` 打开终端聊天界面，支持切群、同步、翻页、回复、@ 成员、图片预览和复制；
  所有群里新收到的 @机器人 消息会显示 8 秒弹窗，不响铃也不自动回复。
- 在收到的图片预览中按 `S` 手动收藏；通过 `/stickers` 预览和发送全局共享的表情。
- QQ 确认发送后写入同一 SQLite 数据库；失败或结果不明确时不自动重试。
- 后台只提供回环地址管理 API、健康检查和带短时签名的单文件取图接口。

本项目不自动回复群消息，不注册 AI 指令，也不提供浏览器用户界面。

## 安装和运行

```bash
cd /home/ubuntu/FisoChat
uv sync --locked
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，至少设置：

```dotenv
QQ_BOT_APPID=...
QQ_BOT_SECRET=...
FISOCHAT_ADMIN_TOKEN=...
FISOCHAT_STICKER_PUBLIC_BASE_URL=https://chat.example.com/fisochat
FISOCHAT_STICKER_SIGNING_SECRET=...
```

管理 Token 和表情签名密钥应分别生成：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

先检查配置，再启动后台和终端：

```bash
uv run fisochat --check-config
uv run fisochat serve
# 在另一个 TTY 中
uv run fisochat
```

`uv run python -m fisochat.main` 也可启动后台。终端可使用
`--env-file /path/to/.env`、`--endpoint http://127.0.0.1:8789` 和
`--group GROUP_OPENID`。通过 SSH 运行时需要分配 TTY，例如 `ssh -t`。

QQ 群管理员需要在机器人资料页开启“接收所有消息”。QQ 只推送开启之后的新消息，
不提供更早历史的补拉接口。同一机器人账号不要同时运行多个网关进程。

## 终端操作

输入消息后按 Enter 发送，按 Shift+Enter 手动换行；粘贴多行文本时会保留原有换行。
以 `/` 开头的是命令；要发送斜杠正文，以 `//` 开头。
命令和 @ 成员候选可用上下键选择、Tab 补全、Esc 收起。

| 快捷键 / 命令 | 操作 |
| --- | --- |
| `/groups`、`Ctrl+G` | 临时打开群组选择器 |
| `/image [记录号 [图片序号]]` | 预览图片；左右键切换，`R` 重试，`S` 收藏 PNG/JPEG |
| `/stickers` | 打开全局表情库；上下键选择，Enter 发送，Esc 返回 |
| `/use 2`、`/use 群ID` | 切换群组 |
| `/older`、`Ctrl+L` | 加载更早的 50 条记录 |
| `/refresh`、`Ctrl+R` | 立即同步 |
| `/reply 记录号` | 指定回复，再输入正文 |
| `@`、`/at 记录号` | 从当前已加载消息中选择要 @ 的成员 |
| `/name`、`Ctrl+N` | 临时展开完整昵称 |
| 鼠标拖选、`Ctrl+C` | 选择并复制聊天记录，不影响草稿 |
| `F1`、`/help` | 打开帮助 |
| `Ctrl+Q`、`/quit` | 退出终端，后台继续运行 |

终端在群之间保留未发送草稿和 @ 选择。发送失败会保留正文；发送连接中断时会要求先检查群
消息记录，不会自动重发。当前界面每群最多保留 2000 条记录。
启动终端时会以现有消息建立 @ 提醒基线，不重放历史提醒；临时断线恢复后只提示本终端尚未
见过的新记录。

终端自动检测 Kitty / Sixel 图片协议；不支持时使用彩色色块。可通过
`--image-mode blocks` 强制色块预览。图片按需下载到内存，限制为 10 MB、2000 万像素和
20 秒总时长，并拒绝内网、本机、带凭据地址和 DNS 重绑定。

## 表情库

在一条未撤回的接收图片上执行 `/image`，按 `S` 才会收藏当前图片。接收、预览和列出图片
都不会自动保存。仅接受经验证的 PNG 和 JPEG；GIF、WebP 等格式仍可预览，但不能收藏。

表情默认保存到 `data/stickers/`：

- 文件名是原始图片字节的 SHA-256 加 `.png` 或 `.jpg`，相同内容只保存一次。
- 目录权限为 `0700`，文件权限为 `0600`，写入使用同目录临时文件和原子替换。
- 表情库在所有群之间共享，发送目标始终是打开选择器时的活动群。
- 应用不提供删除或重命名。删除表情时直接移除对应文件；下次列表或发送会立即反映结果。
- 非法文件名、损坏文件、摘要不符、扩展名不符、非普通文件和符号链接会被忽略。

QQ 群图片上传只接受公开 URL。发送表情时，后台生成 5 分钟有效的 HMAC-SHA256 HTTPS
地址供 QQ 获取。签名 URL、签名密钥和本地路径不会写入消息记录。

## HTTP 边界

以下接口只允许来自 `127.0.0.1` 或 `::1` 的请求，并要求
`Authorization: Bearer <FISOCHAT_ADMIN_TOKEN>`：

- `GET /internal/groups`
- `GET /internal/group-messages?group=GROUP_OPENID`
- `POST /internal/group-messages`
- `POST /internal/stickers`
- `GET /internal/stickers`
- `GET /internal/stickers/{id}`
- `POST /internal/stickers/{id}/send`

收藏接口只接收 `group_openid`、数据库 `record_id` 和一基的 `attachment_index`，由后台查找
真实附件；不接受任意 URL。表情发送接口只接收活动群和表情 ID。

公网只开放 `GET /health` 和
`GET /stickers/{id}?expires=...&signature=...`。签名接口没有目录列表，过期、篡改、未知文件或
额外参数均返回 404。Nginx 模板不会代理任何 `/internal/*` 接口。

命令行发送仍可使用：

```bash
uv run fisochat-send --group GROUP_OPENID --text '消息内容'
uv run fisochat-send --group GROUP_OPENID --reply-to MESSAGE_ID --text '指定回复'
printf '从标准输入发送' | uv run fisochat-send --group GROUP_OPENID
```

## 数据和升级

消息默认保存在 `data/group_messages.db`。FisoChat 使用
`(group_openid, message_id)` 作为唯一键，并会在启动时检查和升级旧单表数据库。非空旧库会先
通过 SQLite backup API 创建 `<数据库>.pre-composite-key.bak`，权限为 `0600`。

升级前停止旧进程，不要并行运行新旧版本。启用 WAL 时不要只复制运行中的 `.db` 主文件。
当前 AiQQ 的事件账本数据库不能直接作为 `FISOCHAT_DB`；详情见
[数据库审计](docs/database-audit-2026-09-16.md) 和 [提取记录](MIGRATION.md)。

## 配置

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `QQ_BOT_APPID` / `QQ_BOT_SECRET` | 必填，QQ 机器人凭据 |
| `FISOCHAT_DB` | `data/group_messages.db` |
| `FISOCHAT_WEB_HOST` / `FISOCHAT_WEB_PORT` | `127.0.0.1` / `8789`，后台 HTTP 监听地址 |
| `FISOCHAT_ADMIN_TOKEN` | 必填，本机终端与命令行管理 Token |
| `FISOCHAT_ADMIN_TOKEN_FILE` | 可替代直接 Token，文件权限必须为 `0600` |
| `FISOCHAT_STICKER_DIR` | `data/stickers` |
| `FISOCHAT_STICKER_PUBLIC_BASE_URL` | 必填，不含凭据、查询或片段的 HTTPS 外部前缀 |
| `FISOCHAT_STICKER_SIGNING_SECRET` | 必填，至少 32 字节且独立于管理 Token |
| `FISOCHAT_HTTP_TIMEOUT_SECONDS` | `30`，范围 5–120 |
| `FISOCHAT_GATEWAY_RESTART_TIMEOUT_SECONDS` | `90`，持续断线后退出，由 systemd 重启 |
| `FISOCHAT_LOG_LEVEL` | `INFO` |

仍接受数据库、HTTP 监听、管理 Token 和超时设置对应的旧 AiQQ 别名；已移除的页面账号配置
不再读取。

## 部署与验证

`deploy/fisochat.service` 默认使用 `/home/ubuntu/FisoChat`，且只允许写入该目录下的 `data/`。
首次部署：

```bash
mkdir -p data/stickers
chmod 700 data data/stickers
sudo cp deploy/fisochat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fisochat
```

将 `deploy/nginx-fisochat-locations.conf` 放入现有 HTTPS `server` 后，先执行 `nginx -t`，
再进行受控重载。`FISOCHAT_STICKER_PUBLIC_BASE_URL` 必须与外部 `/fisochat` 前缀一致。

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv lock --check
uv build
```

测试使用临时目录、临时 SQLite 数据库和模拟 QQ API，不会向真实 QQ 群发送消息。
上线后由操作员检查 `/fisochat/health`、拒绝未签名的表情 URL，并在明确授权后手动验证一次
收藏和发送。回滚时恢复旧代码和 Nginx 配置；旧版本会忽略 `data/stickers/`，无需数据库恢复。
