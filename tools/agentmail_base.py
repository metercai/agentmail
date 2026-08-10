"""agentmail_base — Runtime: preprocessor, hooks, profile, templates."""
from __future__ import annotations
import json
import logging
import os
import re
import secrets
import hashlib
import threading
import time
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any



logger = logging.getLogger(__name__)
_TOOLSET = "agentmail"

# ── persona 能力开关（跨 agent 系统共享，接入新系统时按能力设置）────
# True  = 支持 persona：派生地址 {role}.{profile}@{domain} 保留 + 配置校验 +
#         LLM session 前 persona 切换（Hermes 全能力，默认值）
# False = 不支持 persona：角色 = 独立 agent，收件地址归一为基础地址
#         （OpenClaw 等：agentmail_base 被 import 后由系统层设 False）
# 处理逻辑框架一致，差异仅由本开关驱动——preprocess 内部读取。
PERSONA_SUPPORTED = True



# ═══════════════════════════════════════════════════════════════
# a2a_board helpers — template filling, role/context utilities
# ═══════════════════════════════════════════════════════════════


def fill_template(text: str, ctx: dict) -> str:
    """Replace {{KEY}} placeholders with values from ctx (keys uppercase)."""
    for key, val in ctx.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def _read_role_file(name: str) -> str:
    """Read a2a_board role file from ~/.agentmail/a2a_board/skills/role/<name>.md.
    Falls back to 'common.md' if the named role file is not found."""
    cfg = _load_profile_config()
    sid = cfg.get("system_id", "default") if cfg else "default"
    role_dir = Path.home() / ".agentmail" / sid / "board" / "role_prompt"
    # Try exact match first
    p = role_dir / f"{name}.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    # Fallback to common.md
    common = role_dir / "common.md"
    if common.exists():
        logger.info("[a2a_board] role '%s' not found, using common.md", name)
        return common.read_text(encoding="utf-8")
    logger.warning("[a2a_board] role file not found: %s (common.md also missing)", name)
    return ""


def build_ctx(payload: dict, headers: dict) -> dict:
    """Build template context dict from available data."""
    return {
        "AGENTMAIL_ADDRESS": payload.get("my_amail_addr", ""),
        "BOARD_ID": payload.get("board_id", ""),
        "BOARD_ROLE": payload.get("board_role", ""),
        "FROM_ROLE": payload.get("from_role", ""),
        "INQUIRY_SENDER": payload.get("from", ""),
        "INQUIRY_SUBJECT": payload.get("subject", ""),
        "SOUL_MD_CONTENT": _read_soul_md(),
        "SKILLS_LIST": ", ".join(_read_skills()),
    }


# ── Config helpers ──

def _agentmail_system_dir(system_id: str = "") -> Path:
    """Return ~/.agentmail/{system_id}/ for config storage.
    
    When system_id is empty, returns ~/.agentmail/ itself."""
    base = Path.home() / ".agentmail"
    return base / system_id if system_id else base


def _gateway_config_path(system_id: str = "") -> Path:
    """Return path to the gateway config file.
    
    When system_id is provided, returns system-specific path.
    When empty, returns the base ~/.agentmail/ level (caller should resolve system_id)."""
    return _agentmail_system_dir(system_id) / "amail_gateway.json"


def _load_gateway_config(system_id: str = "") -> Optional[dict]:
    """load gateway connection config

    Reads from (in priority order):
    1. Environment variables (AMAIL_GATEWAY_URL + AMAIL_ADMIN_KEY/AMAIL_PRODUCT_CODE)
    2. ~/.agentmail/{system_id}/amail_gateway.json (direct, or via HERMES_PROFILE_DIR/.agentmail pointer)
    """
    # Try environment variables first
    gateway_url = os.environ.get("AMAIL_GATEWAY_URL", "")
    admin_key = os.environ.get("AMAIL_ADMIN_KEY", "")
    product_code = os.environ.get("AMAIL_PRODUCT_CODE", "")
    sys_id = os.environ.get("AMAIL_SYS_ID", "")
    system_id = sys_id or os.environ.get("AMAIL_TENANT_ID", "")
    mx_domain = os.environ.get("AMAIL_MX_DOMAIN", "amail.token.tm")
    domain = mx_domain or os.environ.get("AMAIL_DOMAIN", "")
    # Fallback: map AMAIL_BRIDGE_URL → webhook_host
    raw_webhook = os.environ.get("AMAIL_WEBHOOK_HOST", "") or os.environ.get("AMAIL_BRIDGE_URL", "")
    if raw_webhook:
        # Strip protocol and /path to get host:port
        raw_webhook = raw_webhook.replace("http://", "").replace("https://", "").split("/")[0]
    if gateway_url and (admin_key or product_code):
        return {
            "gateway_url": gateway_url,
            "admin_key": admin_key,
            "product_code": product_code,
            "system_id": system_id,
            "domain": domain,
            "manager_address": os.environ.get("AMAIL_MANAGER_ADDRESS", ""),
            "webhook_host": raw_webhook,
            "sys_id": sys_id,
            "mx_domain": mx_domain,
        }

    # Try ~/.agentmail/{system_id}/amail_gateway.json
    resolved_sid = system_id
    if not resolved_sid:
        # Resolve from HERMES_PROFILE_DIR/.agentmail pointer
        profile_dir = _PROFILE_DIR_RESOLVER() if _PROFILE_DIR_RESOLVER else None
        if profile_dir:
            pointer = Path(profile_dir) / ".agentmail"
            if pointer.is_file():
                try:
                    pointer_data = json.loads(pointer.read_text())
                    resolved_sid = pointer_data.get("system_id", "")
                except Exception:
                    pass
        if not resolved_sid:
            raise RuntimeError(
                "system_id not provided and HERMES_PROFILE_DIR/.agentmail not found "
                "-- cannot locate gateway config"
            )

    gw_path = _gateway_config_path(resolved_sid)
    if gw_path.is_file():
        try:
            cfg = json.loads(gw_path.read_text())
            if cfg.get("gateway_url") and (cfg.get("admin_key") or cfg.get("product_code")):
                return cfg
        except Exception:
            pass

    return None


# ── 注入点（适配层设置；Hermes → tools/hermes/agentmail_hermes.py，
#             OpenClaw → tools/openclaw/amail_base.py）────────────────
# 平台差异（config 来源/personas/profile 目录/board 登记）由适配层注入，
# 公共核心保持平台无关。未注入时使用安全默认（None/空/no-op）。
_CONFIG_LOADER = None          # () -> Optional[dict]      agent 配置加载
_PERSONAS_PROVIDER = None      # () -> dict                personas 配置
_PROFILE_DIR_RESOLVER = None   # () -> Optional[str]       profile 目录（gateway config 定位）
_SOUL_PROVIDER = None          # () -> str                 SOUL 内容（board ctx）
_SKILLS_PROVIDER = None        # () -> list[str]           skills 列表（board ctx）
_BOARD_GATEWAY_SINK = None     # (board_id, gateway_url) -> None
_BOARD_CRED_SINK = None        # (board_id, gateway_url, token) -> None


def _read_soul_md() -> str:
    """SOUL 内容（注入点）。Hermes 适配层注入；默认空。"""
    return _SOUL_PROVIDER() if _SOUL_PROVIDER is not None else ""


def _read_skills() -> list:
    """skills 列表（注入点）。Hermes 适配层注入；默认空。"""
    return _SKILLS_PROVIDER() if _SKILLS_PROVIDER is not None else []


def _load_profile_config() -> Optional[dict]:
    """agent 配置加载（注入点）。适配层注入平台实现；未注入返回 None
    （preprocess 走 'not configured' 分支）。"""
    if _CONFIG_LOADER is not None:
        return _CONFIG_LOADER()
    return None


def list_personas() -> dict:
    """personas 配置（注入点）。默认空（无 persona 配置）。"""
    if _PERSONAS_PROVIDER is not None:
        return _PERSONAS_PROVIDER()
    return {}


def _register_board_gateway(board_id: str, gateway_url: str) -> None:
    """board 网关注册（注入点）。Hermes 适配层注入写 profile_cfg；默认 no-op。"""
    if _BOARD_GATEWAY_SINK is not None:
        _BOARD_GATEWAY_SINK(board_id, gateway_url)


def _store_board_credential(board_id: str, gateway_url: str, token: str) -> None:
    """board 凭据存储（注入点）。Hermes 适配层注入；默认 no-op。"""
    if _BOARD_CRED_SINK is not None:
        _BOARD_CRED_SINK(board_id, gateway_url, token)


def _put_contact_profile(address: str, profile: str) -> dict:
    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "agentmail not configured for this profile"}
    client = _GatewayClient(config["gateway_url"], config["api_key"])

    result = client.put_contact(address, profile)
    if result.get("status") == 200:
        return {"success": True}
    error = result.get("error", f"HTTP {result.get('status')}")
    return {"success": False, "error": f"Failed to store profile: {error}"}




# ═══════════════════════════════════════════════════════════════
# Gateway Preprocessor — inbound mail payload transformation
# ═══════════════════════════════════════════════════════════════

def preprocess_mail_payload(payload: dict, headers: dict) -> dict:
    """Preprocess agentmail webhook payload before prompt rendering.

    Rust backend already handles text cleaning. Python side handles:

    _extract_board_gateway(payload)  # board gateway URL registry
    - Persona extraction from 'to' address (persona.profile@domain format)
    - Persona validation against configured personalities
    - direct_message / mentioned (persona-aware matching)
    - attachment download
    """
    result = dict(payload)
    body = result.get("body", "")

    if not body:
        logger.warning("[agentmail_gateway] body is empty in raw payload — keys=%s", list(payload.keys())[:12])

    # Agent identity (for direct_message / mentioned)
    config = _load_profile_config()
    agent_email = config.get("email", "") if config else ""
    system_name = config.get("system_name", "") if config else ""

    if not agent_email:
        logger.warning("[agentmail_gateway] No email configured for this profile — inbound preprocessing skipped")
        # Still return a recognizable payload so the gateway continues
        result["_preprocess_error"] = "agentmail email not configured"
        return result

    # ── Extract display names from headers before stripping ──
    import re as _re
    _name_re = _re.compile(r'^(.+?)\s*<')
    _email_re = _re.compile(r'<([^>]+)>')

    def _parse_header_addrs(header_val: str):
        results = []
        for part in header_val.split(','):
            part = part.strip()
            if not part:
                continue
            m = _email_re.search(part)
            if m:
                email = m.group(1).strip().lower()
                nm = _name_re.match(part)
                name = nm.group(1).strip() if nm else email.split('@')[0]
            elif '@' in part:
                email = part.strip().lower()
                name = email.split('@')[0]
            else:
                continue
            results.append((name, email))
        return results

    def _to_list(v):
        if isinstance(v, list):
            return [s.strip() for s in v if s and s.strip()]
        if isinstance(v, str):
            return [s.strip() for s in v.split(',') if s.strip()]
        return []

    def _base_email(email: str) -> str:
        """Strip persona prefix: support.alice@agent.com -> alice@agent.com"""
        persona, profile, sys_name = parse_amail_persona(email, system_name)
        domain = email.split('@', 1)[1] if '@' in email else ''
        if sys_name:
            return f"{profile}.{sys_name}@{domain}"
        return f"{profile}@{domain}"

    to_raw = _to_list(result.get("to", []))
    cc_raw = _to_list(result.get("cc", []))

    # Extract display names from MIME headers
    raw_headers = result.get("headers", {}) or {}
    to_named = _parse_header_addrs(raw_headers.get("to", ""))
    cc_named = _parse_header_addrs(raw_headers.get("cc", ""))

    def _fmt(n, e): return f"{n} <{e}>" if n else e

    if to_named:
        to_display = [_fmt(n, e) for n, e in to_named]
    else:
        to_display = to_raw
    if cc_named:
        cc_display = [_fmt(n, e) for n, e in cc_named]
    else:
        cc_display = cc_raw
    result["recipients"] = {"to": to_display, "cc": cc_display}

    # Bare emails for matching
    to_bare = [e for _, e in to_named] if to_named else [a.lower() for a in to_raw]
    cc_bare = [e for _, e in cc_named] if cc_named else [a.lower() for a in cc_raw]

    # Set sender field with display name (SKILL.md defines "sender", not "from")
    from_named = _parse_header_addrs(raw_headers.get("from", ""))
    if from_named:
        result["sender"] = _fmt(from_named[0][0], from_named[0][1])

    # ── Persona extraction from 'to' address ──
    # Find the recipient that belongs to our agent domain
    agent_domain = agent_email.split('@', 1)[1] if agent_email and '@' in agent_email else ''
    my_to_addr = ''
    for addr in to_bare:
        if agent_domain and addr.endswith('@' + agent_domain):
            my_to_addr = addr
            break

    persona, profile, _sys_name = parse_amail_persona(my_to_addr, system_name) if my_to_addr else ('', '', '')
    if persona:
        if not PERSONA_SUPPORTED:
            # 系统不支持 persona：收件地址归一为基础地址（剥离 persona 前缀），
            # 不做配置校验与派生地址保留——agent 身份即注册的基础地址。
            result["my_amail_addr"] = agent_email
        else:
            # Validate persona against configured personalities
            configured = list_personas()
            if persona in configured:
                result["my_amail_addr"] = my_to_addr
            else:
                logger.warning("[agentmail_gateway] Persona '%s' not found in agent.personalities — falling back to base address", persona)
                # 未配置 persona：剥离 persona 前缀，回退注册基础地址（与创建端幂等）
                result["my_amail_addr"] = agent_email
    if not result.get("my_amail_addr"):
        result["my_amail_addr"] = my_to_addr or agent_email

    # ── Persona-aware direct_message / mentioned ──
    if agent_email:
        agent_email_lower = agent_email.lower()
        agent_base = _base_email(agent_email_lower)
        all_bare = to_bare + cc_bare
        all_base = [_base_email(a) for a in all_bare]

        # DM: only one to-recipient, and it's us (persona-aware)
        result["direct_message"] = (
            len(to_bare) == 1
            and not cc_bare
            and all_base[0] == agent_base
        )

        # mentioned: match profile name and display name
        agent_local = agent_email.split('@')[0]
        agent_display = ''
        for n, e in to_named + cc_named:
            if _base_email(e) == agent_base and n:
                agent_display = n
                break
        match_targets = [agent_local, profile] if profile else [agent_local]
        if agent_display:
            match_targets.append(agent_display)
        body_lower = (body or "").lower()
        result["mentioned"] = any(
            f'@{t.lower()}' in body_lower or t.lower() in body_lower.split()
            for t in match_targets if t
        ) if agent_email else False
    else:
        result["direct_message"] = False
        result["mentioned"] = False

    attachments = result.get("attachments")

    if attachments and isinstance(attachments, list) and len(attachments) > 0:
        # Use profile api_key (agent scope) instead of admin_key for
        # download_attachment — the admin_key may have agent_admin scope
        # which does not include agent-level attachment access.
        profile = _load_profile_config()
        agent_key = (profile or {}).get("api_key", "")
        if not agent_key:
            logger.warning("[agentmail_gateway] Cannot download attachments: no agent api_key in profile")
            return result

        config = _load_gateway_config()
        if not config:
            logger.warning("[agentmail_gateway] Cannot download attachments: no gateway config")
            return result

        client = _GatewayClient(config["gateway_url"], agent_key)
        local_paths = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            att_id = att.get("attachment_id", att.get("id", ""))
            fname = att.get("filename", att.get("name", "unnamed_attachment"))
            if not att_id:
                continue

            content = client.download_attachment(att_id)
            if content is None:
                continue

            # Save to cache directory
            cache_dir = Path.home() / ".hermes" / "cache" / "attachments"
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_path = cache_dir / fname
            # Avoid overwriting -- append counter if needed
            if local_path.exists():
                stem, suffix = local_path.stem, local_path.suffix
                counter = 1
                while local_path.exists():
                    local_path = cache_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            local_path.write_bytes(content)
            local_paths.append(str(local_path))

            # Convert binary documents to markdown (DOCX, XLSX, PDF, HTML)
            ext = Path(fname).suffix.lower()
            if ext in (".docx", ".xlsx", ".html", ".htm"):
                try:
                    from markitdown import MarkItDown
                    md_text = MarkItDown().convert(str(local_path)).text_content
                    if md_text.strip():
                        md_path = cache_dir / f"{Path(fname).stem}.md"
                        md_path.write_text(md_text)
                        local_paths.append(str(md_path))
                except Exception:
                    pass  # keep original, agent falls through to PDF skill

        result["attachments"] = local_paths

    # ── Strip backend-only fields not in SKILL.md to avoid LLM confusion ──
    for field in ("mail_id", "to", "cc", "headers", "created_at", "forwarder", "forward_at"):
        result.pop(field, None)

    # ── Store message metadata + optional raw snapshot ──────────
    mid = result.get("message_id", "")
    refs = result.get("references", [])
    my_addr = result.get("my_amail_addr", "")
    if mid and my_addr:
        store_inbound_message(mid, refs, my_addr, preprocessed_payload=result)
        # Lightweight log entry
        _from = raw_headers.get("from", payload.get("from", ""))
        _subj = (raw_headers.get("subject") or raw_headers.get("Subject")
                 or payload.get("subject") or payload.get("Subject") or "")
        _log_amail("inbound", str(_from), my_addr, str(_subj))

    # ── a2a_board: [WhoAmI]问询检测 ──
    subject = (payload.get("subject") or "").strip()
    if subject.upper().startswith("[WHOAMI]"):
        ctx = build_ctx(result, dict(headers))
        whoami_raw = _read_role_file("whoami")
        if whoami_raw:
            result["_whoami_prompt"] = fill_template(whoami_raw, ctx)
        result["_whoami_update_public"] = True
        return result

    # ── a2a_board: Board上下文检测（由Rust A2aInterceptor注入 board_id / board_role）──
    board_id = result.get("board_id")
    board_role = result.get("board_role")
    if board_id and board_role:
        ctx = build_ctx(result, dict(headers))
        role_raw = _read_role_file(board_role)
        if role_raw:
            result["_role_prompt"] = fill_template(role_raw, ctx)
        sender = result.get("from", "")
        result["_a2a_session_key"] = f"a2a:{board_id}:{sender}"

    return result


# ═══════════════════════════════════════════════════════════════
# Profile Hook System
# ═══════════════════════════════════════════════════════════════

_profile_hooks: Dict[str, List[Callable]] = {
    "profile_created": [],
    "profile_deleted": [],
}


# ── Hook: auto-register email on profile creation ──────────────

def parse_amail_persona(email: str, system_name: str = "") -> tuple:
    """Parse persona, profile, and system_name from an agentmail address.
    
    Returns (persona, profile_name, sys_name).
    
    Shared domain (three-part: persona.profile.sys_name@domain):
      'support.ql-biopharm.myco@amail.token.tm'  → ('support', 'ql-biopharm', 'myco')
      'ql-biopharm.myco@amail.token.tm'           → ('', 'ql-biopharm', 'myco')
      'myco@amail.token.tm'                       → ('', 'default', 'myco')  ← short form
    
    Non-shared domain (two-part: persona.profile@domain):
      'support.alice@agent.com'  → ('support', 'alice', '')
      'alice@agent.com'          → ('', 'alice', '')
    """
    local = email.split('@')[0] if '@' in email else email
    parts = local.split('.')
    
    # If system_name is known and local part matches → short form (default agent)
    if system_name and len(parts) == 1 and parts[0] == system_name:
        return ('', 'default', system_name)
    
    # Three-part: persona.profile.sys_name@domain
    if system_name and len(parts) >= 2 and parts[-1] == system_name:
        sys_name = parts[-1]
        profile_parts = parts[:-1]
        if len(profile_parts) >= 2:
            return ('.'.join(profile_parts[:-1]), profile_parts[-1], sys_name)
        return ('', profile_parts[0], sys_name)
    
    # Traditional: persona.profile@domain
    if len(parts) >= 2:
        return ('.'.join(parts[:-1]), parts[-1], '')
    return ('', parts[0], '')


# ── Board gateway URL registry ──
_board_gateways: dict = {}
_board_gateways_lock = threading.Lock()

def _extract_board_gateway(payload: dict):
    """Extract board_id and gateway_url from board notification emails."""
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    from_addr = payload.get("from", "")
    if ".a2a@" not in from_addr and not subject.startswith("[A2A]"):
        return
    token_match = re.search(r'Token:\s*(bdt_\S+)', body)
    gw_match = re.search(r'API:\s*(https?://\S+)', body)
    if not gw_match:
        return
    gateway_url = gw_match.group(1).rstrip()
    from_match = re.search(r'(\S+)\.a2a@', from_addr)
    if not from_match:
        return
    board_short_id = from_match.group(1)
    gw_domain = re.search(r'://([^/]+)', gateway_url)
    domain = gw_domain.group(1) if gw_domain else ""
    board_id = hashlib.sha256(f"{board_short_id}:{domain}".encode()).hexdigest()[:20]
    _register_board_gateway(board_id, gateway_url)
    if token_match:
        token = token_match.group(1).rstrip()
        _store_board_credential(board_id, gateway_url, token)

# ═══════════════════════════════════════════════════════════════
# 生命周期公共链（注册/注销 agent 地址——跨 agent 系统统一，
# Hermes 适配层与 OpenClaw 注册脚本共用，修订只改此处）
# ═══════════════════════════════════════════════════════════════

def email_for_agent(agent_id: str, domain: str, system_name: str = "",
                    default_aliases: tuple = ("default",)) -> str:
    """agent 地址派生（跨系统统一规则 + 注册前合规清洗）。

    1. 默认名归一：**各系统自己的默认 agent 名** → "agent"
       （Hermes 传 ("default",)，OpenClaw 传 ("main",)；互不替换——Hermes 的
       "main" profile 保持 "main"，OpenClaw 的 "default" agent 保持 "default"）。
    2. 非法字符清洗（作用于**原始地址名** base 段，不含共享域 system_name 标识名）：
       - '.' → '_' **全系统严格统一**（点是 persona 分隔符保留位 + gateway 点规则：
         shared 恰 1 点 / non-shared 0 点，base 含点必拒；与 persona 支持无关）
       - 其他非 atext-no-dot 字符 → '_'（字符集 = gateway is_atext_no_dot）
       - 清洗后为空 → 回退 "agent"
    """
    base = "agent" if agent_id in default_aliases else agent_id
    # 严格清洗：非 atext-no-dot 字符（含 '.'）→ '_'；空结果回退 "agent"
    cleaned = re.sub(r"[^A-Za-z0-9!#$%&'*+\-/=?^_`{|}~]", "_", base)
    base = cleaned or "agent"
    if system_name:
        return f"{base}.{system_name}@{domain}"
    return f"{base}@{domain}"


def register_agent_email(client, system_id: str, email: str,
                         webhook_url: str = "", webhook_secret: str = "",
                         manager_address: str = "", mx_domain: str = "") -> dict:
    """注册链（幂等，4 步）：register_email(generate_code) → 已存在更新 webhook →
    manager 白名单 → activate_address。返回 {"api_key", "activation_code"}
    （api_key 为空 = 激活 pending/已存在；activation_code 供延迟激活语义）。

    client 须提供：register_email / list_system_domains / update_system_domain /
    add_whitelist / activate_address（agentmail_tools._GatewayClient 全具备）。
    """
    result = client.register_email(
        system_id=system_id, mx_domain=mx_domain, email=email,
        webhook_url=webhook_url, webhook_secret=webhook_secret,
        manager_address=manager_address, generate_code=True,
    )
    activation_code = ""
    if isinstance(result, dict):
        activation_code = result.get("activation_code", "") or ""
        status = result.get("status", "")
        if status and str(status) not in ("created", "200", "201", 200, 201):
            msg = str(result.get("error", "")) + str(result.get("detail", ""))
            if "already exists" in msg.lower() or "exists" in msg.lower():
                activation_code = ""
                # 已存在 → 更新 webhook 配置（幂等）
                try:
                    domains = client.list_system_domains(system_id)
                    for d in (domains if isinstance(domains, list) else []):
                        if isinstance(d, dict) and d.get("domain") == email:
                            client.update_system_domain(str(d.get("id", "")),
                                                        webhook_url, webhook_secret)
                            break
                except Exception:
                    pass
            else:
                raise RuntimeError(f"register failed: {result}")

    if manager_address:
        client.add_whitelist(system_id=system_id, domain_addr=email,
                             direction="all", value=manager_address,
                             description="Agent ↔ Manager (auto-created)")

    api_key = ""
    if activation_code:
        act = client.activate_address(activation_code, email_address=email)
        if act.get("success") and act.get("raw_key"):
            api_key = act["raw_key"]
    return {"api_key": api_key, "activation_code": activation_code}


def deregister_agent_email(client, system_id: str, email: str,
                           manager_address: str = "") -> dict:
    """注销链（API 部分，幂等）：api-key → domain → whitelist。
    返回各步状态 {api_key, domain, whitelist}。

    client 须提供：get_api_key_by_email / delete_api_key / list_system_domains /
    delete_whitelist_by_value。
    """
    out: dict = {}
    # 1. 删 API key（按 email 查 id）
    try:
        k = client.get_api_key_by_email(email)
        if isinstance(k, dict) and k.get("id"):
            r = client.delete_api_key(k["id"])
            out["api_key"] = str(r.get("status", r))
        else:
            out["api_key"] = "not_found"
    except Exception as e:
        out["api_key"] = f"err:{e}"

    # 2. 删 domain entry（按 id，回退按名）
    try:
        domains = client.list_system_domains(system_id)
        addr_id = ""
        for d in (domains if isinstance(domains, list) else []):
            if isinstance(d, dict) and d.get("domain") == email:
                addr_id = str(d.get("id", ""))
                break
        if addr_id:
            r = client._request("DELETE", f"/api/v1/admin/systems/{system_id}/domains/{addr_id}")
            out["domain"] = str(r.get("status", r))
        else:
            r = client._request("DELETE", f"/api/v1/admin/systems/{system_id}/domains/{email}")
            out["domain"] = str(r.get("status", r))
    except Exception as e:
        out["domain"] = f"err:{e}"

    # 3. 白名单清理（按值删）
    try:
        if manager_address and hasattr(client, "delete_whitelist_by_value"):
            client.delete_whitelist_by_value(email, manager_address)
        out["whitelist"] = "attempted"
    except Exception as e:
        out["whitelist"] = f"err:{e}"

    return out


# ── 跨模块引用兜底（适配层注入之外的保险）────────────────────────
# preprocess/工具链引用 agentmail_tools 的 3 个符号（模块级名字查找）。
# 双平台适配层（agentmail_hermes / amail_base）会显式注入；此处兜底保证
# 任何入口（直接 import base 的脚本等）也不因加载顺序触发 NameError。
# 循环依赖注意：若 tools 正在初始化（部分加载），from-import 会 ImportError，
# 交给适配层注入兜住；若 base 先加载完成，这里直接成功。
try:
    from agentmail_tools import _GatewayClient, store_inbound_message, _log_amail  # noqa: F401,E402
except ImportError:
    pass

