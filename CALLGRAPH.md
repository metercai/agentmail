# integrate.sh 调用关系

```
integrate.sh  (入口 / entry point)
│
├── source lib/i18n.sh              ── 双语字符串定义
├── source lib/helpers.sh           ── UI 函数 (step_*, info, ask_param)
│
├── Step 1: 配置网关
│   └── python3 lib/print_banner.py ── 标题横幅
│
├── Step 2: 域名 / 系统激活
│   ├── python3 lib/list_domains.py ── 列出已有域名
│   └── (product code 路径)
│       └── python3 lib/activate_system.py ── 产品码激活
│
├── Step 3: 基本配置
│   └── (纯交互，无子模块调用)
│
├── Step 4: 保存配置 + 部署 bridge
│   └── python3 lib/setup_system.py      ── 配置写入 + CLI 入口
│   └── python3 lib/deploy_bridge.py   ── bridge 下载/启动
│
├── Step 5: 安装工具 (source)
│   └── source lib/install-tools.sh    ── 复制 amail_tools.py + 注册技能
│
├── Step 6: 配置 Hermes (source)
│   └── source lib/configure_hermes.sh
│       ├── source lib/patch-webhook.sh    ── webhook.py 打补丁
│       ├── source lib/patch-profiles.sh   ── profiles.py 打补丁
│       ├── python3 lib/register_profiles.py  ── 注册已有 profile 的邮件地址
│       │   └── from amail_tools import _auto_register_email
│       └── source lib/hermes_gateway.sh   ── 启动多 profile 网关
│
├── Step 7: 诊断
│   └── python3 lib/check_status.py     ── 4 层管道检查
│   └── python3 lib/check_status.py --ping  ── 心跳测试
│
└── Step 8: 收发测试
    └── python3 lib/send_welcome.py     ── SMTP 发信 + 轮询回复
```

## 补充调用

```
uninstall.sh
└── python3 lib/uninstall_hermes.py  ── 回滚集成
```

## 说明

- **source** = 在 integrate.sh 进程内加载（共享变量）
- **python3** = 子进程执行（仅通过 env var / stdout 传参）
- Step 5/6 用 `source` 是因为需要读写 caller 的变量（`$HERMES_DIR` 等）
- Step 4/7/8 用 `python3` 是因为是独立的一次性操作
