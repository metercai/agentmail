# 集成后全局协同视图

## 1. 部署后的稳定态

```
┌────────────────────────────────────────────────────────┐
│                     amail-gateway                        │
│  (远程服务器，接收 SMTP 邮件)                              │
│  system_domains 表:                                      │
│    domain_addr="agent@domain.com"                        │
│    webhook_url=""                    ← pull 模式(空)     │
│    webhook_url="http://1.2.3.4:38081/webhooks/..."  ← push│
│    webhook_secret="hmac-key"                             │
└────────────┬──────────────────────┬───────────────────┘
             │ push                 │ pull
             │ POST webhook_url     │ 存 pending_deliveries
             ▼                      ▼
┌────────────────────┐    ┌────────────────────┐
│    amail-bridge     │    │    amail-bridge     │
│  (bridge / direct)  │    │  (自建 pull 模式)    │
│  addr=0.0.0.0:38081 │    │  addr=0.0.0.0:38081 │
│  hostname=公网:port  │    │  mode=pull          │
│  mode=push           │    │                     │
│                      │    │  轮询 GET /pending   │
│     │                │    │     │               │
│     ▼                │    │     ▼               │
│  路由表(amail_routes. │    │  路由表(amail_routes.│
│  toml):               │    │  toml):              │
│  agent@domain.com     │    │  agent@domain.com    │
│  → 127.0.0.1:8645     │    │  → 127.0.0.1:8645    │
│     │                │    │     │               │
└─────┼────────────────┘    └─────┼───────────────┘
      │                           │
      │ POST http://127.0.0.1:8645/webhooks/amail-inbound
      │ X-Webhook-Signature (HMAC)
      │ X-Amail-Email: agent@domain.com
      ▼
┌────────────────────────────────┐
│    Hermes gateway (Python)      │
│  aiohttp :8645 (profile 端口)    │
│  /webhooks/amail-inbound        │
│     │                           │
│     ├─ HMAC 验签                │
│     ├─ rate limit               │
│     ├─ preprocess="amail_gateway"│
│     │   └─ preprocess_mail_payload│
│     │      下载附件/富化 payload   │
│     ├─ 渲染 prompt              │
│     └─ 注入 skill → agent       │
└────────────────────────────────┘
```

## 2. 配置文件全景

```
~/.hermes/
├── amail_gateway.json    ← integrate.sh 写入 (全局)
│   { gateway_url, admin_key, system_id,
│     domain, webhook_host }
│
├── amail_bridge.toml     ← integrate.sh 写入 (bridge 配置)
│   { addr, hostname, mode, tls_* }
│
├── profiles/
│   └── default/
│       ├── config.yaml           ← Hermes gateway 写入 (webhook 端口)
│       │   platforms.webhook.extra.port = 8645
│       │
│       ├── amail.json            ← _auto_register_email 写入
│       │   { email, activation_code, gateway_url,
│       │     domain, _wh_port }
│       │
│       └── webhook_subscriptions.json  ← _ensure_webhook_route
│           { routes: { "amail-inbound": { preprocess:"amail_gateway", ... } } }
│
└── amail_routes.toml      ← bridge update_route() 写入
    { "agent@domain.com" = { host="127.0.0.1", port=8645 } }
```

## 3. 邮件到达 → Agent 全流程

```
外部 SMTP 邮件到达 amail-gateway
  │
  ▼
1. 网关接收 (webhook.rs)
   ├─ 解析收件人 → agent@domain.com
   ├─ resolve_domain_by_name("domain.com")
   ├─ 查 system_domains 表:
   │   webhook_url = ?
   │
   ├─ webhook_url 为空?
   │   YES → pull 模式
   │         签名 payload
   │         插入 pending_deliveries 表
   │         → bridge 轮询时拉取
   │
   └─ webhook_url 非空?
       YES → push 模式
             构造 X-Webhook-Signature (HMAC-SHA256)
             HTTP POST {webhook_url}
               头: X-Amail-Email, X-Webhook-Signature, X-Mailrelay-Timestamp
               体: 签名+富化后的 JSON
  │
  ▼
2. bridge 接收/转发
   │
   ├─ push: 收到 POST /webhooks/*name
   │        查路由表: agent@domain.com → 127.0.0.1:8645
   │        POST http://127.0.0.1:8645/webhooks/amail-inbound
   │
   └─ pull: 轮询 GET /api/v1/admin/pending
            逐个 delivery:
              查路由表 → POST 本机 webhook
             ACK: POST /api/v1/admin/pending/ack
  │
  ▼
3. Hermes gateway 接收
   POST http://127.0.0.1:8645/webhooks/amail-inbound
   ├─ HMAC 验签 (X-Webhook-Signature vs profile webhook_secret)
   ├─ Rate limit (默认 30 req/s)
   ├─ JSON 解析
   ├─ route_config.preprocess == "amail_gateway"?
   │   YES → PREPROCESS_REGISTRY["amail_gateway"](payload)
   │          preprocess_mail_payload():
   │            - 下载附件到本地
   │            - 提取文本内容
   │            - 构造结构化 payload
   │
   ├─ 渲染 prompt (用 email 模板)
   ├─ 注入 skill (如果路由配置了 skills)
   └─ 分发给 agent → LLM 处理
  │
  ▼
4. Agent 收到消息
   邮件以 webhook 事件形式呈现
   Agent 可调用:
     send_mail()        ← 回复/发送
     manage_contacts()  ← 管理联系人
     email_summary()    ← 查看邮件摘要
```

## 4. 生命周期事件流程

```
集成阶段 (integrate.sh, 一次性)
  Step 1-3: gateway_url, auth, domain
  Step 4: webhook 模式 → bridge 部署/验证 → 写入 amail_gateway.json
  Step 5: 保存配置
  Step 6-7: 安装 tools + patch webhook.py
  Step 8: 注册已有 profile (_auto_register_email)
  Step 9-10: 诊断 + 发送测试

Profile 创建时 (Hermes profile hooks)
  _auto_register_email 触发:
    ├─ 读 amail_gateway.json
    ├─ webhook_host=""? → 直连 Hermes
    │   或
    │   → POST bridge /api/v1/routes (注册路由)
    │   → 拿 webhook_url
    ├─ POST gateway /addresses (注册地址 + 生成激活码)
    └─ 写 amail.json: { email, activation_code, _wh_port }

Agent 启动时 (Hermes agent hooks)
  _auto_activate_profile 触发:
    ├─ 检查端口变化 → 必要时 POST bridge /api/v1/routes 更新
    └─ 用 activation_code 激活地址 → 获取 api_key
```

## 5. 关键常量/变量流

```
                 integrate.sh Step 4
                 ┌──────────────────┐
                 │ GATEWAY_URL 本机? │
                 └───┬──────────┬───┘
                YES  │          │  NO (3 选项)
                     │          │
            webhook_host=""      │
                     │    ┌──────┼──────┐
                     │    │      │      │
                     │  [1]    [2]    [3]
                     │ direct internal bridge
                     │    │      │      │
                     │    └──────┼──────┘
                     │           │
                     │    webhook_host="ip:port"|"host:port"
                     │           │
                     ▼           ▼
              amail_gateway.json.webhook_host
                     │
                     │ (只读)
                     ▼
              _auto_register_email
                ├─ webhook_host="" ? 直连 : 调 bridge API
                ├─ bridge API 返回 webhook_url
                └─ POST gateway: webhook_url → system_domains 表
                                           │
                                           ▼
                                  gateway webhook.rs
                                  webhook_url 判空 ⇒ push/pull
```
