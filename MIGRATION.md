# AiQQ 功能提取记录

## 目标和范围

在独立目录中复制群消息推送接收、终端操作和消息发送功能，保持 SQLite 格式。
新项目默认端口 8789、数据库 `data/group_messages.db`，仅依赖自身源码和声明的 Python 依赖。

## 来源映射

| AiQQ 来源 | FisoChat 位置 | 处理 |
| --- | --- | --- |
| `src/aiqq/database/{connection,group_messages,migrations,models}.py` | `src/fisochat/database/` | 复制并调整包名，保留原数据库兼容查询 |
| `src/aiqq/interfaces/qq/gateway.py` | `src/fisochat/interfaces/qq/gateway.py` | 复制原始推送捕获、重连监测 |
| `src/aiqq/interfaces/web/admin_messages.py` | `src/fisochat/interfaces/web/admin_messages.py` | 复制并扩展本机终端 API 和指定回复检查 |
| `src/aiqq/services/qq/sender.py` | `src/fisochat/services/qq/sender.py` | 保留实际发送与落库逻辑，以及原有消息类型辅助方法 |
| `src/aiqq/logic/{models,ports}.py` | `src/fisochat/logic/` | 仅提取消息相关模型和接口 |
| `scripts/send_group_message.py` | `src/fisochat/send.py`、`scripts/send_group_message.py` | 提取命令行发送工具，新增安装入口，匹配新端口和配置 |
| 数据库、管理接口、网关、发送器的单元测试 | `tests/` | 同步迁移，另补独立应用集成测试 |

配置、应用组装、运行入口和 QQ 客户端按独立项目重新连接。客户端仅接收并记录群消息，
删除 AI 会话、内容审核、生图、页面和指令面板的依赖；后台 HTTP 服务在 QQ 登录前启动，
使网关异常时终端仍能读取已有记录和健康状态。

## 验收

1. 独立安装、构建，不导入 `aiqq` 或原项目文件。
2. QQ 原始消息（含未 @ 消息）写入临时数据库，重复事件不产生重复行。
3. 回环地址终端 API 的鉴权、分页、附件和引用投影正常。
4. 终端与命令行管理 API 经发送器调用 QQ，确认成功后入库；错误不自动重复发送。
5. 指定回复必须来自当前群、五分钟内、明确 @ 机器人，并有可用回复序号。
6. 服务启动、网关断线和关闭时，数据库及 HTTP 资源正常释放。

真实 QQ 网关和主动发送权限需要部署者填写机器人凭据后验证。本次提取不执行真实群发送。

## 单表数据库完整性升级

FisoChat 已将旧模型的全局 `UNIQUE(message_id)` 改为
`UNIQUE(group_openid, message_id)`，避免不同群出现相同消息 ID 时互相覆盖。网关重复事件由
数据库仓库统一择优：保留明确的 `GROUP_AT_MESSAGE_CREATE` 类型，payload 独立按完整度选择，
便捷字段保守补全；空值不会清除已有字段，已有撤回标记不会被重复写入清除。机器人发送记录
使用首次成功投影，同群重复插入不会改写记录。

升级在仓库初始化期间完成，早于 HTTP 服务和 QQ 登录。旧库非空时先创建
`<数据库文件名>.pre-composite-key.bak`，使用 SQLite backup API 包含 WAL 中已提交内容，
以 `0600` 权限一次性发布且不会覆盖已有有效旧单表备份。已有备份必须是独立文件，不能是源库的
硬链接。表重建在一个事务内显式保留 `record_id`、所有旧字段和 `sqlite_sequence`；复制数量、
记录号范围、复合唯一键、自增序列和外键检查任一失败都会回滚。
旧 schema、迁移完成的 schema 和 schema 版本标记均会在每次首次初始化时检查。

当前 AiQQ 的 `group_message_events`、`message_versions`、`message_attachments`、
`message_event_processing` 或 `message_delivery_attempts` 表表示事件账本数据库。FisoChat 会在
配置写入模式前拒绝该数据库，而不是绕过账本直接更新投影视图。此次升级没有移植 AiQQ 的完整
事件、版本和投递模型。

部署和恢复命令见 [README 的“升级验证与回滚”](README.md#升级验证与回滚)。恢复时必须停止
服务，并隔离现有主文件及 WAL/SHM 辅助文件后再复制独立备份；不要复制或覆盖运行中的 SQLite
主文件。

## 交互终端扩展

`fisochat` 默认进入 Textual 交互终端，`fisochat serve` 启动后台。
systemd 使用固定的 `python -m fisochat.main` 服务入口，后台与终端分别管理生命周期。
终端通过已有本机管理 Token 读取群列表和消息、执行发送，不直接打开数据库或连接 QQ 网关。
读取接口仅输出消息展示字段，分页支持向前加载和按升序增量补取；终端使用字面文本渲染，
过滤聊天消息中的控制字符，不解析富文本标记或执行聊天内容。

`/image [记录号 [图片序号]]` 通过 Textual Image 和 Pillow 临时预览已有图片附件，
省略参数时打开当前群已加载记录中最近一条未撤回图片消息的最后一张图片。
自动选择 Kitty / Sixel 协议或彩色色块；不支持的终端可用 `--image-mode blocks` 强制色块。
图片下载使用独立的无凭据 HTTP 会话，不携带后台管理 Token，不缓存到磁盘；
连接前检查目标与 DNS 解析结果，逐跳检查重定向，限制公网地址、下载大小、时长和像素数。
关闭预览取消下载并释放图片资源，后台路由和 QQ 网关无需更改。

终端输入框增加本地斜杠命令补全：输入 `/` 时临时显示匹配项，支持上下键选择、
Tab 补全、参数用法提示和 Esc 收起。补全只修改输入框，完整命令仍经原有处理函数执行。

终端支持 `@` 成员补全和 `/at 记录号`，从当前群已加载记录中选择成员。
输入框为已选成员保留文本位置和消息引用，编辑昵称时取消选择，周围文字编辑时更新位置；
随各群草稿保留选择。管理发送 API 验证消息引用属于当前群且为有效成员，允许已收到消息的
其他机器人，排除 FisoChat 自身发送的记录及已撤回、缺少成员标识的记录，生成 QQ 的
`<qqbot-at-user id="成员OpenID" />` 内容，使用 Markdown（`msg_type=2` / `markdown.content`）
完成主动发送或指定回复，避免普通文本原样显示标签。其余正文转义为字面文字，
发送成功后保存包含可读昵称的正文。成员 OpenID 保留在后台，
读取接口仅新增 `can_mention` 标志。没有新增群成员列表接口或数据库迁移。
