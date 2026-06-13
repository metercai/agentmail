# 云主机 amail-advanced 目录结构

```
/usr/local/bin/
  └── amail-advanced         16M  release 二进制

/etc/amail-gateway/
  └── config.toml             用户自行维护的配置文件

/var/amail/
  ├── amail.db                SQLite 数据库
  ├── amail.db.admin_key      自动写入的 admin_key（base 版启动时生成）
  ├── amail.db-shm            SQLite WAL 共享内存文件
  ├── amail.db-wal            SQLite WAL 日志文件
  └── attachments/            邮件附件存储目录
       └── yyyy/mm/dd/        按日期分目录（自动创建）

/var/log/
  └── amail-gateway.log       daemon 模式日志

/var/run/
  └── amail-gateway.pid       daemon PID 文件

/etc/systemd/system/
  └── amail-gateway.service   systemd 单元文件（可选）
```

## 用户维护 vs 自动创建

| 文件 | 维护者 | 说明 |
|------|--------|------|
| `config.toml` | 用户 | 启动前准备好 |
| `amail-advanced` | deploy.sh 上传 | 一次性 |
| `amail.db*` | 二进制自动创建 | 首次启动生成 |
| `attachments/` | 二进制自动创建 | 按需 |
| `.admin_key` | 二进制自动写入 | base 版首次启动生成 (advanced 版不生成) |
| 日志/PID | 二进制或 systemd | daemon 模式 |

## deploy.sh 命令

```bash
export AMAIL_DEPLOY_HOST="46.17.41.218"
export AMAIL_DEPLOY_KEY="~/.ssh/id_deploy"

# 上传二进制
bash deploy.sh upload

# 启动（底层调用 amail-advanced --daemon）
bash deploy.sh start

# 查看状态
bash deploy.sh status

# 停止
bash deploy.sh stop
```
