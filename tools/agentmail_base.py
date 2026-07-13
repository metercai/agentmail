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


"""
agentmail_tools.py -- agentmail Hermes Agent 运行时模块

Hermes 运行时加载的模块，提供：
  - _GatewayClient         : HTTP client for agentmail API
  - send_mail()            : Agent tool -- send email via gateway
  - manage_contacts()      : Agent tool -- manage address whitelist
  - contact_profile()      : Agent tool -- look up contact
  - set_contact_profile()  : Agent tool -- update contact profile
  - email_summary()        : Agent tool -- read thread summary
  - set_email_summary()    : Agent tool -- write thread summary
  - preprocess_mail_payload() : Gateway preprocessor -- inbound mail handling
  - register_profile_hook()   : Profile lifecycle hook registry
  - trigger_profile_hooks()   : Hook dispatcher (called by profiles.py)

Toolset: agentmail
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime
import socket
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

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


def _read_soul_md() -> str:
    """Read SOUL.md from current Hermes profile."""
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if not profile_dir:
        profile_dir = str(Path.home() / ".hermes")
    soul = Path(profile_dir) / "SOUL.md"
    if soul.exists():
        return soul.read_text(encoding="utf-8")
    return ""


def _read_skills() -> list[str]:
    """Read loaded skills list from profile config."""
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if not profile_dir:
        profile_dir = str(Path.home() / ".hermes")
    cfg = Path(profile_dir) / "config.yaml"
    if cfg.exists():
        import yaml
        try:
            data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            return data.get("skills", []) or []
        except Exception:
            pass
    return []


def _resolve_agent_email() -> str:
    """Resolve current agent's email from profile config."""
    from tools.agentmail_tools import _load_profile_config as _lpc
    cfg = _lpc()
    if cfg:
        return cfg.get("email", "") or cfg.get("domain", "")
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


# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════



        result = self._request("POST", "/api/v1/activate-address", body=body)
        raw_key = result.get("raw_key", "")
        if not raw_key:
            return {"success": False, "error": f"activation failed: {result}"}
        return {
            "success": True,
            "raw_key": raw_key,
            "api_key_id": result.get("api_key_id", 0),
            "email_address": result.get("email_address", ""),
        }


# ═══════════════════════════════════════════════════════════════
# Config helpers
# ═══════════════════════════════════════════════════════════════

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
        profile_dir = _resolve_profile_dir()
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


def _resolve_profile_dir() -> Optional[str]:
    """Resolve Hermes profile directory via fallback chain.

    1. HERMES_PROFILE_DIR env var (explicit override, highest priority)
    2. Hermes runtime get_hermes_home() (contextvar-aware, multi-profile)
    3. ~/.hermes/ (default profile, ultimate fallback)
    """
    pdir = os.environ.get("HERMES_PROFILE_DIR", "")
    if pdir:
        return pdir
    try:
        from hermes_constants import get_hermes_home
        home = get_hermes_home()
        if home:
            return str(home)
    except Exception:
        pass
    default = Path.home() / ".hermes"
    if default.is_dir():
        return str(default)
    return None


def _load_profile_config() -> Optional[dict]:
    """Load per-profile gateway config from centralized agentmail directory.
    
    Uses {profile_dir}/.agentmail pointer → {system_id}/ path:
      Root profile:  ~/.agentmail/{system_id}/agentmail.json
      Named profile: ~/.agentmail/{system_id}/profiles/{name}/agentmail.json
    """
    profile_dir = _resolve_profile_dir() or ""
    
    search_paths = []

    if profile_dir:
        # Priority 1: .agentmail pointer → structured path
        pointer = Path(profile_dir) / ".agentmail"
        if pointer.is_file():
            try:
                pointer_data = json.loads(pointer.read_text())
                sid = pointer_data.get("system_id", "")
                if sid:
                    pname = Path(profile_dir).name
                    hermes_home = Path.home() / ".hermes"
                    is_root = Path(profile_dir).resolve() == hermes_home.resolve()
                    if is_root:
                        search_paths.append(
                            _agentmail_system_dir(sid) / "agentmail.json"
                        )
                    else:
                        search_paths.append(
                            _agentmail_system_dir(sid) / "profiles" / pname / "agentmail.json"
                        )
            except Exception:
                pass

    for config_path in search_paths:
        if config_path.is_file():
            try:
                return json.loads(config_path.read_text())
            except Exception:
                pass
    
    return None


def _inject_profile_config(profile_dir: str, config: dict) -> None:
    """Write per-profile agentmail config.

    Root profile:  ~/.agentmail/{system_id}/agentmail.json
    Named profile: ~/.agentmail/{system_id}/profiles/{name}/agentmail.json
    Pointer file:  {profile_dir}/.agentmail  (contains system_id for discovery)

    Merges with existing config — preserves fields not in the new config
    (e.g. api_key from previous activation).
    """
    system_id = config.get("system_id", "")
    pname = Path(profile_dir).name

    # Detect root profile: profile_dir is HERMES_HOME
    hermes_home = Path.home() / ".hermes"
    is_root = Path(profile_dir).resolve() == hermes_home.resolve()

    # Write primary config to centralized agentmail directory
    if system_id:
        if is_root:
            primary = _agentmail_system_dir(system_id) / "agentmail.json"
        else:
            primary = _agentmail_system_dir(system_id) / "profiles" / pname / "agentmail.json"
        primary.parent.mkdir(parents=True, exist_ok=True)
        # Merge with existing — preserve fields like api_key
        existing = {}
        if primary.exists():
            try:
                existing = json.loads(primary.read_text())
            except Exception:
                pass
        merged = {**existing, **config}
        # Prevent activation_code + api_key coexistence
        if merged.get("api_key") and merged.get("activation_code"):
            merged.pop("activation_code", None)
        primary.write_text(json.dumps(merged, indent=2))

    # Write .agentmail pointer for discovery
    pointer_path = Path(profile_dir) / ".agentmail"
    pointer_path.write_text(json.dumps({
        "system_id": system_id,
        "email": config.get("email", ""),
    }, indent=2))


# ── Webhook config helpers (gateway-managed, per-profile) ─────────

def _port_is_available(port: int, host: str = "0.0.0.0") -> bool:
    """Check if a TCP port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.bind((host, port))
            return True
    except OSError:
        return False


def _read_webhook_port(cfg_path: Path) -> int:
    """Read webhook port from a profile config file. Returns 0 if not found."""
    if not cfg_path.exists():
        return 0
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        wh = cfg.get("platforms", {}).get("webhook", {})
        if wh.get("enabled"):
            return int(wh.get("extra", {}).get("port", 0))
    except Exception:
        pass
    return 0


def _next_available_webhook_port(base_port: int = 8644) -> int:
    """Find the next available webhook port.
    
    Scans all existing profile configs for the max port, then probes
    actual port availability. Increments until an unused port is found.
    """
    # Scan existing profiles for max configured port
    max_port = base_port - 1
    default_cfg = Path.home() / ".hermes" / "config.yaml"
    max_port = max(max_port, _read_webhook_port(default_cfg))
    profiles_dir = Path.home() / ".hermes" / "profiles"
    if profiles_dir.is_dir():
        for d in profiles_dir.iterdir():
            if d.is_dir():
                max_port = max(max_port, _read_webhook_port(d / "config.yaml"))
    
    # Start after max configured port, probe actual availability
    candidate = max(max_port + 1, base_port)
    for _ in range(100):  # safety limit
        if _port_is_available(candidate):
            return candidate
        candidate += 1
    return candidate  # fallback — likely all ports exhausted


def _ensure_profile_webhook(profile_dir: str) -> Optional[dict]:
    """Ensure the profile has webhook configured. Auto-generates if missing.
    
    Returns {enabled, host, port, secret} or None on fatal error.
    """
    cfg_path = Path(profile_dir) / "config.yaml"
    
    # Already configured? Return existing
    if cfg_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            wh = cfg.get("platforms", {}).get("webhook", {})
            if wh.get("enabled"):
                extra = wh.get("extra", {})
                return {
                    "enabled": True,
                    "host": extra.get("host", "0.0.0.0"),
                    "port": int(extra.get("port", 8644)),
                    "secret": extra.get("secret", ""),
                }
        except Exception as e:
            logger.warning("[agentmail_gateway] Failed to read webhook config: %s", e)
    
    # Auto-generate
    port = _next_available_webhook_port()
    secret = secrets.token_hex(32)
    
    try:
        import yaml
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if cfg_path.exists():
            existing = yaml.safe_load(cfg_path.read_text()) or {}
        
        # Deep-merge with existing config
        platforms = dict(existing.get("platforms", {}))


    """
    profile_dir = _resolve_profile_dir() or ""
    if profile_dir:
        try:
            import yaml
            profile_cfg_path = Path(profile_dir) / "config.yaml"
            if profile_cfg_path.exists():
                with open(profile_cfg_path) as f:
                    cfg = yaml.safe_load(f) or {}
                return cfg.get("agent", {}).get("personalities", {}) or {}
        except Exception:
            pass
    return {}



def _ensure_webhook_route(
    route_name: str,
    secret: str,
    profile_dir: str = "",
    skills: Optional[List[str]] = None,
    deliver: str = "log",
    persona: str = "",
) -> bool:
    """Idempotently create/update a webhook route in webhook_subscriptions.json.
    
    Writes to ``{profile_dir}/webhook_subscriptions.json`` so each profile's
    gateway sees its own routes. Falls back to ``HERMES_HOME`` (or ~/.hermes)
    when ``profile_dir`` is empty.

    Returns True if the route was newly created, False if it already existed.
    """
    # Validate persona if specified
    if persona:
        personas = list_personas()
        if persona not in personas:
            logger.warning(
                "[agentmail_gateway] Persona '%s' not found in agent.personalities. "
                "Available: %s. Route will be created without persona.",
                persona, ", ".join(personas.keys()) or "(none)"
            )
            persona = ""  # clear invalid persona

    if profile_dir:
        hermhome = profile_dir
    else:
        hermhome = os.environ.get("HERMES_HOME",
            str(Path.home() / ".hermes"))
    subs_path = Path(hermhome) / "webhook_subscriptions.json"
    subs = {}
    if subs_path.exists():
        try:
            subs = json.loads(subs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass

    existed = route_name in subs

    route_entry = {
        "description": f"agentmail inbound email route ({route_name})",
        "events": [],
        "secret": secret,
        "preprocess": "agentmail_gateway",    # triggers preprocess_mail_payload
        "prompt": "",
        "skills": skills or [],
        "deliver": deliver,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if persona:
        route_entry["persona"] = persona
    subs[route_name] = route_entry

    subs_path.parent.mkdir(parents=True, exist_ok=True)


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

def _extract_board_gateway(payload: dict):
    """Extract board_id and gateway_url from board notification emails.
    ONLY triggers for board emails (sender contains .a2a@ or subject starts with [A2A]).
    Does NOT affect non-board toolset gateway_url."""
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    from_addr = payload.get("from", "")

    # Guard: only board emails
    if ".a2a@" not in from_addr and not subject.startswith("[A2A]"):
        return

    import re
    token_match = re.search(r'Token:\s*(bdt_\S+)', body)
    gw_match = re.search(r'API:\s*(https?://\S+)', body)
    if not gw_match:
        return
    gateway_url = gw_match.group(1).rstrip()

    # Extract board short_id from sender: "shortid <shortid.a2a@domain>"
    from_match = re.search(r'(\S+)\.a2a@', from_addr)
    if not from_match:
        return
    board_short_id = from_match.group(1)

    from hashlib import sha256
    gw_domain = re.search(r'://([^/]+)', gateway_url)
    domain = gw_domain.group(1) if gw_domain else ""
    board_id = sha256(f"{board_short_id}:{domain}".encode()).hexdigest()[:20]
    _register_board_gateway(board_id, gateway_url)
    if token_match:
        token = token_match.group(1).rstrip()
        _store_board_credential(board_id, gateway_url, token)

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
        # Validate persona against configured personalities
        configured = list_personas()
        if persona in configured:
            result["my_amail_addr"] = my_to_addr
        else:
            logger.warning("[agentmail_gateway] Persona '%s' not found in agent.personalities — falling back to base address", persona)
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
        config = _load_gateway_config()
        if not config:
            logger.warning("[agentmail_gateway] Cannot download attachments: no gateway config")
            return result

        client = _GatewayClient(config["gateway_url"], config["admin_key"])
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
# Webhook Preprocessor Registration (Gateway process only)
# ═══════════════════════════════════════════════════════════════

try:
    from gateway.platforms.webhook import register_preprocessor

    register_preprocessor("agentmail_gateway", preprocess_mail_payload)
    logger.info("agentmail preprocessor registered with webhook gateway")


except ImportError:
    # Agent process / CLI process — webhook module unavailable, expected
    pass
except Exception as e:
    logger.warning("agentmail preprocessor registration failed: %s — inbound mail will NOT be preprocessed", e)


# ═══════════════════════════════════════════════════════════════
# Profile Hook System
# ═══════════════════════════════════════════════════════════════

_profile_hooks: Dict[str, List[Callable]] = {
    "profile_created": [],
    "profile_deleted": [],
}


def register_profile_hook(event: str, callback: Callable) -> None:
    """Register a callback for profile lifecycle events."""
    if event not in _profile_hooks:
        _profile_hooks[event] = []
    _profile_hooks[event].append(callback)


def trigger_profile_hooks(event: str, profile_name: str, profile_dir: str) -> None:
    """Called by profiles.py to fire all registered hooks for an event.

    Gracefully handles missing config -- if no gateway is configured, hooks are
    simply skipped.
    """
    try:
        config = _load_gateway_config()
    except RuntimeError:
        logger.debug("[agentmail_gateway] No gateway config -- skipping hooks for %s", event)
        return


    if not config:
        logger.debug("[agentmail_gateway] No gateway config -- skipping hooks for %s", event)
        return

    for cb in _profile_hooks.get(event, []):
        try:
            cb(profile_name, profile_dir, config)
        except Exception as e:
            logger.warning("[agentmail_gateway] hook %s for '%s' failed: %s", event, profile_name, e)


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


def _auto_register_email(name: str, profile_dir: str, config: dict) -> None:
    """When a new Profile is created, register its email with agentmail:
    1. Create domain entry for {name}@{domain}
    2. Create activation code for the agent
    3. Ensure agentmail-inbound webhook route on the gateway
    4. Inject config into profile directory
    
    The registered address is the agent's identity. Persona switching is
    handled at inbound time by parse_amail_persona() — the agentmail skill
    extracts persona from the 'to' address (persona.profile@domain format).
    """
    gateway_url = config.get("gateway_url", "")
    admin_key = config.get("admin_key", "")
    domain = config.get("domain", "")
    system_id = config.get("system_id", "")

    if not gateway_url or not admin_key:
        logger.warning("[agentmail_gateway] Cannot auto-register: gateway_url or admin_key not configured")
        return
    if not domain:
        logger.warning("[agentmail_gateway] Cannot auto-register: domain not configured")
        return
    if not system_id:
        logger.warning("[agentmail_gateway] Cannot auto-register: system_id not configured")
        return

    client = _GatewayClient(gateway_url, admin_key)
    system_name = config.get("system_name", "") or ""
    if system_name:
        email = f"agent.{system_name}@{domain}" if name == "default" else f"{name}.{system_name}@{domain}"
    else:
        email = f"agent@{domain}" if name == "default" else f"{name}@{domain}"
    manager_address = config.get("manager_address", "")

    # Auto-configure or read profile webhook config
    wh_config = _ensure_profile_webhook(profile_dir)
    if not wh_config:
        logger.warning("[agentmail_gateway] Failed to configure webhook for %s — inbound mail disabled", profile_dir)
        webhook_url = ""
        webhook_secret = ""
    else:
        webhook_secret = wh_config["secret"]
        wh_port = wh_config["port"]

        webhook_host = config.get("webhook_host", "")
        if not webhook_host:
            # integrate.sh set webhook_host="" → gateway is local
            webhook_url = f"http://127.0.0.1:{wh_port}/webhooks/agentmail-inbound"
        else:
            # Remote gateway → call bridge API to get webhook_url
            # Protocol: IP:port → http, domain:port → https
            if re.match(r'^(\d+\.\d+\.\d+\.\d+|\[.*\]):', webhook_host):
                bridge_base = f"http://{webhook_host}"
            elif '[' in webhook_host and ']' in webhook_host:
                # IPv6 without port — add default bridge port
                bridge_base = f"http://{webhook_host.rstrip(']')}:38081]"
            elif ':' in webhook_host and '.' not in webhook_host:
                # Raw IPv6 (no brackets) — wrap and add port
                bridge_base = f"http://[{webhook_host}]:38081"
            else:
                bridge_base = f"https://{webhook_host}"

            try:
                import json as _json
                data = _json.dumps(
                    {"email": email, "host": "127.0.0.1", "port": wh_port}
                ).encode()
                req = urllib.request.Request(
                    f"{bridge_base}/api/v1/routes",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    resp_data = _json.loads(r.read().decode())
                webhook_url = resp_data.get("webhook_url", "")
                logger.info("[agentmail_gateway] Bridge returned webhook_url=%s", webhook_url)
            except Exception as e:
                logger.warning("[agentmail_gateway] Bridge unreachable: %s (continuing without bridge webhook)", e)
                # Don't block registration — bridge can be set up later
                webhook_url = ""

        # Ensure agentmail-inbound route exists (idempotent)
        _ensure_webhook_route("agentmail-inbound", webhook_secret, profile_dir=profile_dir)

    # Register the email + generate activation code in one call
    result = client.register_email(
        system_id=system_id,
        mx_domain=config["domain"],
        email=email,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        manager_address=manager_address,
        generate_code=True,
    )
    logger.info("[agentmail_gateway] Registered email %s: %s", email, result)

    if result.get("status") not in ("created", 200, 201):
        msg = str(result.get("error", "")) + " " + str(result.get("detail", ""))
        if "already exists" in msg.lower():
            logger.info("[agentmail_gateway] Email %s already registered — updating webhook config", email)
            # Update webhook_url/webhook_secret on existing domain record
            try:
                domains = client.list_system_domains(system_id)
                items = domains if isinstance(domains, list) else []
                for d in items:
                        if d.get("domain") == email:
                            addr_id = d.get("id")
                            break
                if addr_id:
                    client.update_system_domain(addr_id, webhook_url, webhook_secret)
                    logger.info("[agentmail_gateway] Updated webhook for %s (id=%s)", email, addr_id)
                else:
                    logger.warning("[agentmail_gateway] Cannot find domain ID for %s to update webhook", email)
            except Exception as e:
                logger.warning("[agentmail_gateway] Failed to update webhook for %s: %s", email, e)
        else:
            logger.error("[agentmail_gateway] Failed to register email %s: %s — skipping activation code generation", email, result)
            return

    # Allow agent to send email to its own manager (for contact approval requests)
    if manager_address:
        client.add_whitelist(
            system_id=system_id,
            domain_addr=email,
            direction="all",
            value=manager_address,
            description="Agent ↔ Manager (auto-created)",
        )

        logger.info("[agentmail_gateway] Whitelisted manager %s for agent %s", manager_address, email)

    # Extract activation code from combined response
    activation_code = ""
    if isinstance(result, dict):
        raw = result.get("activation_code", "")
        if raw:
            activation_code = raw

    if not activation_code:
        # Already registered: profile should have existing api_key or activation_code
        logger.info("[agentmail_gateway] Email %s already registered — using existing credentials", email)
        # Don't pass activation_code to inject; merge preserves existing value
        # Check if existing config has a pending activation_code to activate
        try:
            if system_id:
                if name == "default":
                    existing_cfg_path = _agentmail_system_dir(system_id) / "agentmail.json"
                else:
                    existing_cfg_path = _agentmail_system_dir(system_id) / "profiles" / name / "agentmail.json"
                if existing_cfg_path.is_file():
                    existing_cfg = json.loads(existing_cfg_path.read_text())
                    if existing_cfg.get("activation_code") and not existing_cfg.get("api_key"):
                        activation_code = existing_cfg["activation_code"]
                        logger.info("[agentmail_gateway] Found pending activation_code for %s — will activate", email)
        except Exception:
            pass

    inject_cfg = {
        "email": email,
        "gateway_url": gateway_url,
        "domain": config["domain"],
        "system_id": system_id,
        "manager_address": manager_address,
        "save_raw_snapshots": config.get("save_raw_snapshots", False),
        "webhook_host": config.get("webhook_host", ""),
        "webhook_secret": webhook_secret,
        "_wh_port": wh_port if wh_config else 0,
    }
    if activation_code:
        inject_cfg["activation_code"] = activation_code
    _inject_profile_config(profile_dir, inject_cfg)

    # Activate the profile immediately after registration
    if activation_code:
        try:
            _auto_activate_profile(profile_dir, config)
        except Exception as e:
            logger.error("[agentmail_gateway] Activation failed for %s: %s — activation_code retained", email, e)


# ═══════════════════════════════════════════════════════════════
# Hook: auto-activate profile on agent startup
def _auto_activate_profile(profile_dir: str, config: dict) -> None:
    """Activate a pending profile (has activation_code, no api_key yet).

    Called by the agent startup process when it detects an activation code
    in the profile config. This ensures the raw_key is only visible to
    the agent process itself.

    Reads from centralized ~/.agentmail/{system_id}/ path only.
    """
    # Resolve the correct centralized config path
    hermes_home = Path.home() / ".hermes"
    is_root = Path(profile_dir).resolve() == hermes_home.resolve()
    pname = Path(profile_dir).name

    # Read system_id from pointer file to find centralized config
    sid = ""
    pointer_path = Path(profile_dir) / ".agentmail"
    if pointer_path.is_file():
        try:
            pd_data = json.loads(pointer_path.read_text())
            sid = pd_data.get("system_id", "")
        except Exception:
            pass

    if not sid:
        logger.warning(
            "[agentmail_gateway] No system_id in .agentmail pointer for %s — cannot activate",
            profile_dir,
        )
        return

    if is_root:
        config_path = _agentmail_system_dir(sid) / "agentmail.json"
    else:
        config_path = _agentmail_system_dir(sid) / "profiles" / pname / "agentmail.json"

    if not config_path or not config_path.is_file():
        return

    try:
        with open(config_path) as f:
            prof = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    activation_code = prof.get("activation_code", "")
    if not activation_code:
        return  # Already activated or no code

    if prof.get("api_key"):
        # Already has a key -- clean up stale activation_code
        prof.pop("activation_code", None)
        with open(config_path, "w") as f:
            json.dump(prof, f, indent=2)
        return

    client = _GatewayClient(config.get("gateway_url", prof.get("gateway_url", "")),
                          "", timeout=5)
    result = client.activate_address(activation_code, email_address=prof.get("email", ""))
    if result.get("success") and result.get("raw_key"):
        prof["api_key"] = result["raw_key"]
        prof.pop("activation_code", None)
        prof.pop("last_activation_attempt", None)
        with open(config_path, "w") as f:
            json.dump(prof, f, indent=2)
        logger.info("[agentmail_gateway] Activated profile, api_key saved to %s", config_path)

        # ── Sync api_key to centralized config ─────────────────────
        # Only write to the correct centralized path based on profile type:
        #   root profile  → ~/.agentmail/{system_id}/agentmail.json
        #   named profile → ~/.agentmail/{system_id}/profiles/{name}/agentmail.json
        # NEVER write a named profile's key to the root config.
        try:
            pointer_path = Path(profile_dir) / ".agentmail"
            if pointer_path.is_file():
                pd = json.loads(pointer_path.read_text())
                pname = Path(profile_dir).name
                hermes_home = Path.home() / ".hermes"
                is_root = Path(profile_dir).resolve() == hermes_home.resolve()
                sid = pd.get("system_id", "")

                if is_root and sid:
                    root_path = _agentmail_system_dir(sid) / "agentmail.json"
                    if root_path.is_file():
                        root = json.loads(root_path.read_text())
                        root["api_key"] = result["raw_key"]
                        root.pop("activation_code", None)
                        root_path.write_text(json.dumps(root, indent=2))
                        logger.info("[agentmail_gateway] api_key synced to %s", root_path)
                elif not is_root and sid:
                    named_path = _agentmail_system_dir(sid) / "profiles" / pname / "agentmail.json"
                    if named_path.is_file():
                        named = json.loads(named_path.read_text())
                        named["api_key"] = result["raw_key"]
                        named.pop("activation_code", None)
                        named_path.write_text(json.dumps(named, indent=2))
                        logger.info("[agentmail_gateway] api_key synced to %s", named_path)
        except Exception as sync_err:
            logger.warning("[agentmail_gateway] Failed to sync api_key: %s", sync_err)

        # ── Port refresh: re-register bridge route if webhook port changed ──
        webhook_host = config.get("webhook_host", "")
        if webhook_host:


            wh_config = _ensure_profile_webhook(profile_dir)
            if wh_config:
                current_port = wh_config["port"]
                last_port = prof.get("_wh_port", 0)
                if current_port != last_port:
                    if re.match(r'^(\d+\.\d+\.\d+\.\d+|\[.*\]):', webhook_host):
                        bridge_base = f"http://{webhook_host}"
                    else:
                        bridge_base = f"https://{webhook_host}"
                    try:
                        import json as _json
                        data = _json.dumps(
                            {"email": prof["email"], "host": "127.0.0.1", "port": current_port}
                        ).encode()
                        req = urllib.request.Request(
                            f"{bridge_base}/api/v1/routes",
                            data=data,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=5) as r:
                            pass
                        prof["_wh_port"] = current_port
                        with open(config_path, "w") as f:
                            json.dump(prof, f, indent=2)
                        logger.info("[agentmail_gateway] Bridge route updated: port %s -> %s",
                                    last_port, current_port)
                    except Exception as e:
                        logger.warning("[agentmail_gateway] Bridge route refresh failed: %s", e)
    else:
        # Rate-limit retries: skip if recently attempted (avoids spamming gateway
        # with a permanently invalid activation code)
        import time as _time
        now_ts = _time.time()
        last = prof.get("last_activation_attempt", 0)
        if last and (now_ts - last) < 300:
            logger.debug("[agentmail_gateway] Skipping activation retry for %s (last attempt %ds ago)",
                         config_path, int(now_ts - last))
        else:
            prof["last_activation_attempt"] = now_ts
            with open(config_path, "w") as f:
                json.dump(prof, f, indent=2)
            logger.warning("[agentmail_gateway] Failed to activate profile %s: %s",
                           config_path, result.get("error", result))


# ── Hook: auto-deregister email on profile deletion ────────────

def _auto_deregister_email(name: str, profile_dir: str, config: dict) -> None:
    """When a Profile is deleted, clean up its API key in agentmail."""
    gateway_url = config.get("gateway_url", "")
    admin_key = config.get("admin_key", "")
    domain = config.get("domain", "")
    if not gateway_url or not admin_key:
        return

    # Read the profile's config from centralized path to get the email address
    system_id = config.get("system_id", "")
    config_path = None
    if system_id:
        if name == "default":
            cp = _agentmail_system_dir(system_id) / "agentmail.json"
        else:
            cp = _agentmail_system_dir(system_id) / "profiles" / name / "agentmail.json"
        if cp.is_file():
            config_path = cp

    if not config_path:
        return

    try:
        profile_config = json.loads(config_path.read_text())


# ── Board gateway URL registry ──
_board_gateways: dict = {}
_board_gateways_lock = threading.Lock()

def _get_board_gateway_url(board_id: str, profile_cfg: dict) -> str:
    with _board_gateways_lock:
        return _board_gateways.get(board_id, profile_cfg.get("gateway_url", ""))

def _register_board_gateway(board_id: str, gateway_url: str):
    with _board_gateways_lock:
        _board_gateways[board_id] = gateway_url

def _store_board_credential(board_id: str, gateway_url: str, token: str):
    """Persist board credential to file for subprocess access."""
    try:
        import json as _json
        sid = _load_profile_config().get("system_id", "default") if _load_profile_config() else "default"
        creds_path = Path.home() / ".agentmail" / sid / "board_creds.json"
        creds = {}
        if creds_path.exists():
            creds = _json.loads(creds_path.read_text())
        creds[board_id] = {"url": gateway_url, "token": token}
        creds_path.write_text(_json.dumps(creds, indent=2))
    except Exception:
        pass

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
