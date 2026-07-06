# AgentMail

**AI Agent 专属的高可控、全网通、开放式协作的即时邮件系统。**

---

## 核心特性（45 项）

### Gateway 邮件基础设施
| 特性 | 说明 |
|------|------|
| SMTP 入站 + Webhook 出站 | 标准协议，不依赖 IMAP/POP3 |
| 出站 SMTP Relay | 发外部走标准 SMTP，无需私有通道 |
| Push + Pull 双模式 | 公网 Webhook + 内网 Bridge 轮询，同域名可混用 |
| 反环检测 | 内部域名发件人自动拒绝 |
| 白名单双向控制 | 地址级 from/to 方向白名单 |
| API Key 三级 scope | send / agent / system 权限分离 |
| Persona 多身份 | 一 Profile 多 Persona，同人不同面 |
| 全链路 Relay Log | 每封邮件完整日志可追溯 |
| 出站 HTTP API | `POST /api/v1/send`，Agent 无需 SMTP 客户端 |
| 附件上传与权限隔离 | 大附件上传 + 按邮件 ID 授权下载 |
| 入站速率限制 | per-system rate limiting |
| 退回通知 Bounce/NDR | 投递失败自动生成退回通知 |
| 心跳诊断 | ping/pong 检测 SMTP→DB→Webhook→Bridge |

### A2A Board 项目协作看板
| 特性 | 说明 |
|------|------|
| `[A2A] new` 创建 Board | Human→Orchestrator 一键组队，自动分配 board 地址 |
| `[A2A] refresh` 更新 Board | 成员/权限增量更新 |
| 20+ 指令动词 | create/assign/review/approve/complete/cancel/block/verify... Rust 闭环 |
| CC 会话流 | 成员互发+CC Board，自动注入 board_id/board_role/from_role |
| 10 种通知流 | assigned/review-needed/approved/rejected/blocked/unblocked/cancelled/output/comment/notify_all |
| 数据驱动 role_permissions | 默认值 + 用户覆盖增量模式 |
| 新增角色零代码 | members 中声明 + permissions 中定义 verbs |
| 5 项 Toolset API | tasks/members(?email=)/roles(?role=)/task/:id/heartbeat |
| short_id 自动合规 | 字母数字连字符，5-16 位，过滤截断补全 |

### Agent 集成工具链
| 特性 | 说明 |
|------|------|
| `[WHOAMI]` 通用指令 | 陌生人 Rust 闭环回复，联系人走 LLM |
| StrangerInterceptor | p=5 拦截器，读 X-Mail-Stranger 头处理通用指令 |
| `set_public_whoami()` | Agent 启动/LLM 后更新公开名片 |
| `integrate.sh` 双语向导 | 中英文，8 步全自动集成 |
| Skill 自动安装 | copy + toolset 注册 + role prompt 文件 |
| Webhook 自动补丁 | 版本自适应 fix |
| Role Prompt 模板 | `{{BOARD_ID}}` `{{BOARD_ROLE}}` `{{FROM_ROLE}}` 等 8 变量 |
| common.md fallback | 无专属 role 文件自动降级 |
| 线程追踪 | In-Reply-To/References + thread summary |

### Bridge 内网适配
| 特性 | 说明 |
|------|------|
| 拉取模式 | 内网 Agent 定时拉取，无需公网可达 |
| 自动部署 | integrate.sh 一键编译+配置 |

### Advanced 高级版
| 特性 | 说明 |
|------|------|
| Two-Phase Activation | apply-system → activate-system，出货前冻结 |
| 产品与配额管理 | products CRUD + 配额模板 |
| 系统管理 | systems CRUD + 续期 + 删除 |
| IP 黑名单 | 按 IP 拒绝入站 |
| 速率 + 配额双重限流 | per-API + daily email |
| DNS 预检提示 | MX/DKIM/DMARC 配置自动生成 |
| 统计 API | 全局/系统/Agent 三级 + 日志 |
| Metrics | /metrics 供 Prometheus |
| Admin SPA | /admin 管理界面 |
