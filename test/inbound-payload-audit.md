# 入站邮件 JSON 审计：SKILL.md vs 实际后端

## 排查的文件

| 层 | 文件 | 职责 |
|----|------|------|
| Rust 后端 | `src/email/records.rs:178` → `to_webhook_payload()` | 构建原始 payload |
| Rust 后端 | `src/email/records.rs:233` → `enrich_with_contacts()` | 注入 sender_contact / recipient_contacts |
| Rust 后端 | `src/api/webhook.rs:124-142` | 注入 my_role |
| Python 预处理器 | `tools/amail_tools.py:998` → `preprocess_mail_payload()` | 注入 direct_message / mentioned，转换附件 |
| SKILL.md | `integrations/hermes/skill/SKILL.md:42-56` | 告知 LLM 的字段 |

## 对比结果

| 字段 | SKILL.md 声称 | 后端实际发送 | 预处理器后 | 结论 |
|------|--------------|-------------|-----------|------|
| `from` | string ✅ | ✅ | ✅ 保留 | 一致 |
| `subject` | string ✅ | ✅ | ✅ 保留 | 一致 |
| `body` | string ✅ | ✅ | ✅ 保留 | 一致 |
| `attachments` | array[string] (本地路径) | array[object] (attachment_id/filename) | ✅ 转为路径数组 | 一致（预处理器转换） |
| `recipients` | array[string] | ❌ 无此字段，只有 `to`/`cc` string | ❌ 未注入 | **BSKILL.md 说有，实际没有** |
| `direct_message` | boolean | ❌ 无 | ✅ 注入 | 一致（预处理器添加） |
| `mentioned` | boolean | ❌ 无 | ✅ 注入 | 一致（预处理器添加） |
| `sender_contact` | object | ✅ enrich 后注入 | ✅ 保留 | 一致 |
| `recipient_contacts` | array[object] | ✅ enrich 后注入 | ✅ 保留 | 一致 |
| `signature` | string | ✅ 条件注入 | ✅ 保留 | 一致 |
| `my_role` | string | ✅ webhook 处理注入 | ✅ 保留 | 一致 |
| `message_id` | string | ✅ 条件注入 | ✅ 保留 | 一致 |
| `references` | array[string] | ✅ 条件注入 | ✅ 保留 | 一致 |
| `to` | **未提及** ❌ | ✅ string | ✅ 保留 | **多余** — 应用 `recipients` 替代 |
| `cc` | **未提及** ❌ | ✅ string | ✅ 保留 | **多余** — 应用 `recipients` 替代 |
| `mail_id` | **未提及** ❌ | ✅ 始终存在 | ✅ 保留 | **多余** — 后端内部 ID |
| `headers` | **未提及** ❌ | ✅ 始终存在 | ✅ 保留 | **多余** — 完整 SMTP headers |
| `created_at` | **未提及** ❌ | ✅ 始终存在 | ✅ 保留 | **多余** — 时间戳 |
| `forwarder` | **未提及** ❌ | ✅ 始终存在 | ✅ 保留 | **多余** — 中继地址 |
| `forward_at` | **未提及** ❌ | ✅ 始终存在 | ✅ 保留 | **多余** — 时间戳 |

## 结论：需要修正

1. **预处理器缺失 `recipients` 字段注入**：SKILL.md 声明了 `recipients: array[string]`，但预处理器只解析它来计算 `direct_message`，没有写回 payload。
2. **后端冗余字段未剥离**：`mail_id`, `headers`, `created_at`, `forwarder`, `forward_at`, `to`, `cc` 这些字段对 LLM 无意义，甚至可能造成混淆（`to`/`cc` vs `recipients`）。
