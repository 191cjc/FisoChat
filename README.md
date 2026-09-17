# FisoChat

从 `/home/ubuntu/AiQQ` 提取的独立 QQ 群消息工具，使用 Python 3.11+、腾讯官方
`qq-botpy`、aiohttp、SQLite 和 Textual 终端界面。无需 OpenAI、Codex、NovelAI、Node.js 或原项目目录。

## 功能

- **交互式终端**：运行 `fisochat` 打开全屏聊天界面，切换群聊、实时同步、翻看历史、输入发送，支持斜杠命令和键盘操作。
- **聊天记录推送接收**：通过 QQ WebSocket 网关接收 `GROUP_MESSAGE_CREATE` 和
  `GROUP_AT_MESSAGE_CREATE`，保存正文、发送人、时间、附件、引用和完整消息数据，按群和消息 ID 去重；
  同一事件重复到达时保留明确 @ 类型，payload 独立保留信息更完整的版本，空字段不会覆盖已有内容。
- **聊天记录查看**：原项目的网页界面，按群切换、每页 50 条、查看更早记录、图片和引用文本展示，支持手机和深色模式。
- **消息发送**：查看页底部发送普通文本；命令行主动发送，或回复五分钟内的指定 @ 消息。
  QQ 返回消息 ID 后将机器人发出的消息存入同一数据库；发送失败不伪造成功记录、不自动重发。
- **访问控制**：网页 Basic Auth、发送表单 CSRF、本机管理 API 的 Bearer Token，页面不输出原始事件中的隐私字段。
- **独立运维**：健康检查、网关断线监测、systemd 与 Nginx 配置模板、只读网页模式。

这里的“推送”沿用原项目含义：**QQ 将新群消息推送给机器人并入库**，没有新增向第三方平台转发的接口。
本项目不自动回复群消息，不注册 AI 指令。

## 安装和运行

```bash
cd /home/ubuntu/FisoChat
uv sync --locked
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，填写 `QQ_BOT_APPID`、`QQ_BOT_SECRET`、`FISOCHAT_VIEW_PASSWORD`。
如需交互终端或命令行发送，同时设置独立的 `FISOCHAT_ADMIN_TOKEN`，可以使用
`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成。

```bash
uv run fisochat --check-config
uv run fisochat serve
```

打开 <http://127.0.0.1:8789/group-messages>，使用 `.env` 中的用户名和口令登录。
记录默认保存为 `data/group_messages.db`，通过页面刷新按钮读取新记录。
`uv run python -m fisochat.main` 也可以启动后台服务。
可用 `--env-file /path/to/.env` 指定配置文件；已有进程环境变量优先。

QQ 群管理员需要在机器人资料页开启“接收所有消息”。QQ 只推送开启之后的新消息，
不提供更早聊天记录的补拉接口。图片展示使用 QQ 原附件地址，地址过期后需要重新发送图片。
使用相同机器人账号切换到本项目时，先停止旧网关进程，避免两个实例争用会话。

## 交互式终端

本机后台服务已经启动。通过 SSH 登录服务器后执行：

```bash
cd /home/ubuntu/FisoChat
uv run fisochat
```

`fisochat console`、`fisochat-console` 和 `python -m fisochat` 也会打开终端。
首次部署时，先在另一窗口执行 `uv run fisochat serve`，或者使用下文的 systemd 服务。
终端复用后台连接，退出后 QQ 网关继续接收和保存消息。

默认是单栏消息流，每条消息紧凑显示为「时间 · 记录号 · 昵称缩写 › 正文」，底部输入后按 **Enter** 发送。
点击聊天界面的消息区、空白处或提示区后可以直接继续输入；切回终端窗口时也会恢复输入焦点，
保留草稿和光标位置。群聊选择、图片预览等临时界面保持各自的键盘操作。
昵称最多保留前两个字符，较长昵称加省略号；重名缩写加编号区分，同一群内的缩写保持稳定。
原文中的换行显示为 `↵`，超出终端宽度时自然折行。
`/name` 临时展开当前群所有已加载消息的完整昵称及对应缩写，按 **Esc** 或再次输入 `/name` 恢复；
发送消息或切换群聊时也会恢复缩写。
`/groups` 临时打开群聊选择列表，确认或取消后回到消息流，不常驻侧栏。
群组顺序在当前终端会话中保持稳定；每 2 秒同步新消息，断开后自动重连。
切换群组时保留各群草稿，发送失败保留正文；不会自动重试发送。

输入 `/` 会在输入框上方临时显示命令和说明，继续输入会自动筛选，例如 `/re` 匹配
`/refresh` 和 `/reply`。用 **↑↓** 选择、**Tab** 补全，**Esc** 收起提示并保留输入。
未写完的命令按 **Enter** 会先补全，完整命令按 **Enter** 执行；需要参数的命令会留出空格，
并提示用法和示例。例如 `/im` → **Tab** → `/image `，可直接按 **Enter** 查看最近一张图片，或填写消息记录号。
普通消息和以 `//` 开头的正文不显示补全，群聊选择和图片预览继续使用各自的快捷键。

输入 **@** 会临时列出当前群中可选择的成员，继续输入昵称或缩写可筛选；用 **↑↓** 选择，
**Tab / Enter** 确认，随后输入正文并按 **Enter** 发送。也可用 `/at 31` 直接选择消息 31 的发送人。
输入框中使用 `@昵称缩写`，下方的「将 @」提示显示完整昵称；可同时选择多人。
删除或修改对应的 @ 昵称会取消该目标，修改周围正文会保留选择；切群和发送失败时随草稿保留。
只手动输入 `@昵称` 而未从候选中选择，会作为普通文字发送。
候选来自当前群已加载的消息，不是完整群通讯录；找不到时可先用 `/older` 加载历史，
或等待该成员的新消息。有有效成员标识的其他机器人也可选择；FisoChat 自身发送的记录、
已撤回或缺少成员标识的消息不可选择，不提供 @ 全体成员。
发送时后台校验目标属于当前群，再转换为 QQ 的成员 @ 标记；实际投递仍受 QQ 权限和频次限制。

图片、文件显示附件名称和链接，引用文本直接展示。图片消息附有 `/image 记录号` 提示，
执行后临时打开预览；**左右键**切换同条消息中的图片，**Esc / Enter** 返回消息流，**R** 重试加载。
也可以用 `/image 31 2` 直接查看记录 31 的第二张图片。只读取当前群已加载的记录，
更早图片先用 `/older` 加载。预览不会改变草稿、回复对象或昵称显示状态。
直接输入 `/image` 会打开当前群已加载记录中最近一条未撤回图片消息的最后一张图片；
若没有图片，会提示使用 `/older` 加载更早消息。

终端自动检测 Kitty / Sixel 图片协议（如 Kitty、WezTerm、iTerm2 等支持的终端）；
不支持时使用彩色色块作粗略预览。SSH 下取决于本地终端及中间的 tmux 等是否支持图片协议。
如果终端显示异常，可运行 `uv run fisochat --image-mode blocks` 强制使用色块。
图片按比例适应窗口；动图仅显示首帧，原图可通过消息中的链接查看。
预览按需从附件链接下载，只保存在内存；关闭或切换图片时取消未完成的下载。
单图最大 10 MB、2000 万像素，下载最长 20 秒；链接过期、格式不支持等情况会提示原因。

| 快捷键 / 命令 | 操作 |
| --- | --- |
| `/`、`↑↓`、`Tab` | 显示和筛选命令、选择并补全，Esc 收起提示 |
| `@`、`/at 记录号` | 选择要 @ 的成员，确认后输入正文发送 |
| `Ctrl+N`、`/name` | 临时展开完整昵称，Esc 或再次执行恢复缩写 |
| `Ctrl+G`、`/groups` | 临时切群，上下键移动、Enter 选中，Esc 取消 |
| `/image [记录号 [图片序号]]` | 默认预览最近一张；左右键切换，Esc / Enter 返回，R 重试 |
| `/use 2`、`/use 群ID` | 切换群组 |
| `Ctrl+L`、`/older` | 加载更早的 50 条记录 |
| `PageUp` / `PageDown` | 滚动聊天记录 |
| 鼠标拖选、`Ctrl+C` | 选择并复制聊天记录，不影响当前草稿 |
| `Ctrl+R`、`/refresh` | 立即同步 |
| `/reply 记录号` | 指定回复，再输入正文；仍受 QQ 五分钟 @ 回复限制 |
| `/cancel` | 取消指定回复 |
| `F1`、`/help` | 查看帮助 |
| `Escape` | 关闭临时视图、恢复昵称缩写并返回输入框 |
| `Ctrl+Q`、`/quit` | 退出终端 |

以 `/` 开头的输入是终端命令；发送以斜杠开头的正文，请使用 `//`。
每个群的当前界面最多保留 2000 条记录，更早记录可以在网页查看。
单次消息最多 2000 字符，不保存本地输入历史。

终端只需管理 Token 和本机接口地址，不建立额外 QQ 网关连接：

```bash
uv run fisochat --env-file /path/to/.env --group GROUP_OPENID
uv run fisochat console --endpoint http://127.0.0.1:8789
```

需要交互式终端（TTY）；远程单命令启动时使用
`ssh -t 服务器 'cd /home/ubuntu/FisoChat && .venv/bin/fisochat'`。

## 发送消息

网页中选择群，输入 1 至 2000 个字符，点击发送。主动发送需要 QQ 平台对应权限和频次额度。
也可以在运行服务的服务器上执行：

```bash
uv run fisochat-send --group GROUP_OPENID --text '消息内容'
uv run fisochat-send --group GROUP_OPENID --reply-to MESSAGE_ID --text '指定回复'
printf '从标准输入发送' | uv run fisochat-send --group GROUP_OPENID
uv run python scripts/send_group_message.py --group GROUP_OPENID --text '消息内容'
```

命令行接口为 `POST http://127.0.0.1:8789/internal/group-messages`，需要
`Authorization: Bearer <FISOCHAT_ADMIN_TOKEN>`。JSON 字段为 `group_openid`、`content`，
以及可选的 `reply_to_message_id` 和 `mentions`。`mentions` 为最多 20 项的列表，每项包含
`record_id`（当前群中该成员的一条消息）、`start` 和 `end`（正文中所选 @ 文字的字符起止位置，
左闭右开，按 Unicode 字符计数）。后台查找成员标识并生成 `<qqbot-at-user id="成员OpenID" />`，
通过 `msg_type=2` 的 `markdown.content` 发送，主动发送和指定回复均使用该通道，记录中保留可读昵称。
普通正文会转义为 Markdown 中的字面文字，只有明确选择的成员生成 @ 标签。
标签格式依据 [QQ 官方文本交互文档](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html)。
不要将标签放进普通文本的 `content`：实际群消息会将它原样显示，无法形成 @。
终端不接收或填写成员 OpenID。仅接受本机来源，不信任转发头；反向代理只开放部署模板中的
页面与健康路由。发送成功返回 `message_id`、`sent_at` 和 `recorded`。
若 QQ 已确认发送而写库失败，会明确提示，避免重复发送。

终端读取接口是 `GET /internal/groups` 和 `GET /internal/group-messages?group=GROUP_OPENID`，
同样要求本机访问和 Bearer Token，只返回显示所需字段，不暴露原始事件。
收到的 QQ @ 标记会依据同一条消息的 `mentions` 显示为昵称，正文、引用及群预览使用相同规则；
数据库保留原文。没有对应昵称的历史标记保持原样，避免错误归属。
消息接口支持 `before` 或 `after` 记录号和 `limit`（1–100），返回按时间顺序排列的记录；
`after` 从游标之后最早的记录开始分页，确保突发消息不被跳过。这些接口不经公网反向代理开放。

## 已有记录与只读模式

FisoChat 使用 `(group_openid, message_id)` 作为消息唯一键。启动时会识别提取项目时使用
全局 `message_id` 唯一键的旧单表数据库，并在 HTTP 服务和 QQ 网关启动前自动升级。
非空旧库会先通过 SQLite backup API 创建一次性独立备份：若数据库是
`/path/chat.db`，备份为 `/path/chat.db.pre-composite-key.bak`，权限为 `0600`。
已有的有效旧单表备份不会被覆盖；它必须是独立文件，不能是源库的硬链接。已有备份无效、
备份失败、迁移校验失败或 schema 不受支持时，启动会直接失败。
迁移保留全部记录、记录号、原始 payload、撤回状态和自增序列。

当前 AiQQ 已升级为原始事件、消息版本、附件和投递记录组成的账本模型。FisoChat 会明确拒绝
向这种数据库写入，不能直接将当前 AiQQ 数据库配置为 `FISOCHAT_DB`；详见
[数据库审计](docs/database-audit-2026-09-16.md)。如需导入旧单表历史，应先停止源服务，
再使用 SQLite backup API 取得一致快照并让 FisoChat 指向该快照。启用 WAL 时不要只复制
运行中的 `.db` 主文件。
项目创建时没有复制旧项目的凭据或聊天数据，也没有更改旧服务。

只需要查看数据库时，填写网页账号、口令和 `FISOCHAT_DB` 后执行：

```bash
uv run fisochat --web-only
```

此模式不连接 QQ、不开放发送接口，页面隐藏输入框。它仍会初始化数据库、应用兼容迁移，
因此需要数据库可写；检查备份时请使用副本。

### 升级验证与回滚

部署包含数据库迁移的版本时，应安排一次受控重启，不要同时运行新旧两个进程：

```bash
sudo systemctl restart fisochat
journalctl -u fisochat -n 100 --no-pager
sqlite3 data/group_messages.db 'PRAGMA integrity_check; PRAGMA foreign_key_check; PRAGMA user_version;'
```

正常结果包含 `ok`、没有外键违规，并且 schema 版本为 `1`。还可用
`PRAGMA index_list(group_messages);` 确认表已建立复合唯一索引。此检查不会发送 QQ 消息。

如需回滚，先停止服务，将当前数据库及可能存在的 `-wal`、`-shm` 文件一起移入单独的故障保留目录，
再把 `.pre-composite-key.bak` 复制到原 `FISOCHAT_DB` 路径并设为 `0600`，最后使用迁移前的程序版本启动。
不要在服务运行时直接覆盖数据库，也不要让旧 WAL/SHM 文件与恢复后的主文件混用。一次性备份反映首次迁移前的状态；
迁移后新增的消息不会包含在其中，因此回滚前应保留当前文件用于诊断和人工恢复。

## 配置

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `QQ_BOT_APPID` / `QQ_BOT_SECRET` | QQ 机器人凭据，只读模式可空 |
| `FISOCHAT_VIEW_USERNAME` | `admin` |
| `FISOCHAT_VIEW_PASSWORD` | 必填，网页访问口令 |
| `FISOCHAT_DB` | `data/group_messages.db` |
| `FISOCHAT_WEB_HOST` / `FISOCHAT_WEB_PORT` | `127.0.0.1` / `8789` |
| `FISOCHAT_ADMIN_TOKEN` | 可空，留空且无 Token 文件时关闭管理发送 API |
| `FISOCHAT_ADMIN_TOKEN_FILE` | 可空，权限为 `0600` 的 Token 文件 |
| `FISOCHAT_HTTP_TIMEOUT_SECONDS` | `30`，范围 5–120 |
| `FISOCHAT_GATEWAY_RESTART_TIMEOUT_SECONDS` | `90`，持续断线后退出，由 systemd 重启 |
| `FISOCHAT_LOG_LEVEL` | `INFO`，日志输出到控制台 / systemd journal |

迁移时也接受原项目的 `AIQQ_GROUP_MESSAGE_DB`、`AIQQ_GROUP_MESSAGE_VIEW_USERNAME`、
`AIQQ_GROUP_MESSAGE_VIEW_PASSWORD`、`AIQQ_HEALTH_HOST`、`AIQQ_HEALTH_PORT`、
`AIQQ_ADMIN_TOKEN`、`AIQQ_ADMIN_TOKEN_FILE`、`AIQQ_QQ_HTTP_TIMEOUT_SECONDS` 和
`AIQQ_GATEWAY_RESTART_TIMEOUT_SECONDS`。存在对应 `FISOCHAT_` 变量时以新变量为准（包括显式空值）。

## 部署与验证

本机已部署为 `fisochat.service`，启用开机自启，监听 `127.0.0.1:8789`。
公网入口为 <https://www.firesoul.cn/fisochat/>，健康检查为
<https://www.firesoul.cn/fisochat/health>；查看页面使用 `.env` 中配置的管理员账号和口令。
FisoChat 使用 `/fisochat/` 路由，AiQQ 使用 `/aiqq/` 路由。

`deploy/fisochat.service` 假设项目目录为 `/home/ubuntu/FisoChat`、运行用户为 `ubuntu`。
填好配置后可安装服务：

```bash
mkdir -p data
chmod 700 data
sudo cp deploy/fisochat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fisochat
journalctl -u fisochat -f
```

如果更改数据库位置，同时修改服务中的 `ReadWritePaths`。
将 `deploy/nginx-fisochat-locations.conf` 加入现有 HTTPS `server`，执行 `nginx -t` 后重载 Nginx，
即可通过 `/fisochat/group-messages` 访问。公网访问应使用 HTTPS 保护 Basic Auth。

`GET /health` 在数据库已打开且 QQ 网关连接时返回 200；断线时返回 503。
只读模式以数据库状态判断健康，返回 `mode=web_only`。

```bash
uv run python -m unittest discover -s tests -v
uv build
```

测试使用临时 SQLite 数据库和模拟 QQ API，不向真实 QQ 群发送消息。
提取来源与调整说明见 [MIGRATION.md](MIGRATION.md)。
