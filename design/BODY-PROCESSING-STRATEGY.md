# Body Processing Strategy

> Status: Draft for review

## 1. 核心思路：从外到内逐层剥离

邮件 body 是多层嵌套的：

```
L0: 当前发件人正文 + 当前发件人签名
  ↓ 以下为引用（回复/转发）
  L1: 原邮件正文 + 原发件人签名
      ↓ 以下为再转发
      L2: 再原文 + 再原文签名
```

处理顺序：**从外到内逐层分解，每层独立提取签名，引用保留但标记化**。

```
raw_body
  │
  ├── step 1: 识别引用边界
  │     匹配多种分隔标记（见 §5）
  │
  ├── step 2: 分离 L0 和引用块
  │     L0 body = 引用边界之前的内容
  │     quote block = 引用边界及之后的内容
  │
  ├── step 3: 提取 L0 签名
  │     L0 sig = extract_signature(L0 body)
  │     L0 clean = L0 body 去掉签名块
  │
  ├── step 4: 递归处理引用块
  │     inner = process_layer(quote_block)  → 返回 {body, signature, layers}
  │
  └── step 5: 组装最终 body
        L0 clean
        ---
        L0 sig（标记）
        ---
        
        **回复/转发引用:** （标记化，不删除）
        
        > inner.body
        > 
        > **原发件人签名:** inner.sig
```

## 2. MIME 源选择

```
multipart/mixed/alternative/related
  ├── text/plain     → 直接取用（字数充足且内容完整时优先）
  ├── text/html      → HTML→Markdown 转换（plain 短/不完整时启用）
  └── attachments    → 附件列表（含 CID 内嵌图片）
```

**混排策略**：当 text/plain 字数 < text/html 字数 50% 时，启用 HTML→Markdown。

## 3. HTML→Markdown 转换规则

### 3.1 保留结构

| HTML | Markdown |
|------|----------|
| `h1~h6` | `# ~ ######` |
| `b/strong` | `**bold**` |
| `i/em` | `*italic*` |
| `ul/ol/li` | `- / 1.` 嵌套列表 |
| `a href` | `[text](url)` |
| `br/p` | `\n` |
| `table` | 纯文本表格或转列表 |
| `blockquote` | `> quote` |

### 3.2 清理噪声

| 输入 | 处理 |
|------|------|
| `style`/`script` | 删除 |
| `<!-- comment -->` | 删除 |
| MSO/Word 标记（`o:p` 等） | 删除 |
| 内联 `style`/`class`/`id` | 删除 |
| `&nbsp;` `&amp;` `&lt;` | 解码 |

### 3.3 图片处理

| 来源 | 有 alt text | 无 alt text |
|------|------------|-------------|
| CID（MIME 内嵌） | `[IMAGE: alt]` + 附件 | 删除 |
| HTTP(S) 外链 | `![alt](url)` 保留 | `[IMAGE]` |
| data: URI | 缩略（>50KB 则剥离） | 删除 |
| 追踪像素（1x1） | — | 删除 |

## 4. 签名提取

### 4.1 提取时机

```
per-layer 提取，不是全局提取。

每层剥离引用后，该层 body 只剩 [当前层正文 + 当前层签名]。
签名就在末尾，不会被下层干扰。
```

### 4.2 提取规则（现有 Rust `signature.rs` 三层）

| 规则 | 匹配模式 | 置信度 |
|------|---------|--------|
| RFC 3676 | `-- \n` 分隔符 + 后续行 | 0.95 |
| 命名结尾 | "Best regards"+"姓名+职位" | 0.80 |
| 中文落款 | 中文姓名+公司（无分隔符） | 0.65 |

### 4.3 排除误匹配

- 已知声明/安全通知模板后的 `-- ` → 不算签名
- 法律/合规预设文本 → 不算签名
- 超过 20 行 → 不算签名

### 4.4 每层给 agent 的结构

```json
{
  "body": "当前层正文（不含签名，含 [IMAGE] 标记）",
  "signature": {
    "raw": "Simang Daimari\nInternational Onboarding...",
    "separator": "-- ",
    "confidence": 0.95,
    "type": "rfc3676"
  }
}
```

## 5. 引用/转发边界识别

### 5.1 分隔标记

| 语言 | 模式 |
|------|------|
| 英文回复头 | `On ... wrote:` |
| 中文回复头 | `在 ... 写道：` |
| 英文转发 | `--- Forwarded message ---` |
| 中文转发 | `--转发邮件--` / `原始邮件` |
| Outlook | `-----Original Message-----` |
| QQ 邮件 | `------------------ 原始邮件 ------------------` |
| Gmail | `---------- Forwarded message ---------` |
| 通用引用行 | `>` 开头 |

### 5.2 递归算法

```
fn process_layer(body) -> LayerResult:
  quote_pos ← find_first(body, 引用分隔标记)
  if not quote_pos:
    # 最内层，无引用
    clean, sig = extract_sig(body)
    return {body: clean, signature: sig, layers: 1}

  current  = body[:quote_pos]       # Ln 正文
  quoted   = body[quote_pos:]       # Ln+1 引用（递归）

  clean, sig = extract_sig(current)
  inner = process_layer(quoted)     # 递归处理引用

  return {
    body: assemble(clean, sig, inner),
    signature: [sig] + inner.signature,
    layers: 1 + inner.layers
  }
```

## 6. 最终 body 组装格式

```markdown
## 当前邮件

请帮我处理这份申请表...

---

**发件人签名:** Simang Daimari
International Onboarding Case Manager

---

**回复/转发引用:**

> **发件人:** HSBC Online Account
> **发送时间:** 2026年6月20日
> **主题:** HSBC Account Application
>
> Dear Mingjun Cai,
>
> Thank you for your application...
>
> ---
>
> **原发件人签名:** HSBC Customer Service
```

引用内容以 `>` 标记，每层嵌套用 `>` `>>` `>>>` 表示深度。

## 7. 噪声过滤（每层独立）

| 内容 | 处理 |
|------|------|
| 免责声明尾部 | strip（已知模板） |
| 退订/订阅链接 | strip |
| 追踪像素 | strip |
| 空白段落 | collapse |
| 法律声明块 | strip（已知模板） |
| 签名块 | 提取到 signature 字段，body 中用标记代替 |
