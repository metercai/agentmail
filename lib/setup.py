"""
setup.py — amail Hermes 集成安装模块

集成安装阶段的函数（仅在 integrate.sh 流程中调用，不在 Hermes 运行时执行）。
从 amail_tools.py 提取解耦，保持运行时文件干净。

Depends on:
  - tools/amail_tools.py for _GatewayClient, _gateway_config_path, _load_gateway_config
"""

import json
import logging
import os
import socket
import sys
from pathlib import Path

# 将 tools/ 加入 sys.path 以导入 amail_tools
_tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

# 这些是运行时模块，解耦后 setup.py 依赖它们
from amail_tools import (
    _GatewayClient,
    _gateway_config_path,
    _load_gateway_config,
)

logger = logging.getLogger("amail_setup")


# ═══════════════════════════════════════════════════════════════
# Webhook host auto-detection
# ═══════════════════════════════════════════════════════════════

def _detect_webhook_host(gateway_url: str) -> str:
    """Determine the reachable host for gateway → Hermes webhook callbacks.

    Compares ``gateway_url``'s host against local interfaces to choose the
    correct callback address:

    - Same machine (loopback or own IP) → ``127.0.0.1``
    - Same LAN (private IP, different host) → our LAN IP
    - Remote (public IP) → our external IP or LAN fallback

    Returns the best host string.  Failing everything, returns ``127.0.0.1``.
    """
    from urllib.parse import urlparse
    try:
        gateway_host = urlparse(gateway_url).hostname or ""
    except Exception:
        gateway_host = ""

    if not gateway_host:
        return "127.0.0.1"

    # ── Detect our primary LAN IP ────────────────────────────
    lan_ip = ""
    # Best-effort: let the kernel pick the route to an external address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass

    # Fallback: scan interfaces
    if not lan_ip:
        try:
            import subprocess as _sp
            out = _sp.check_output(
                ["ip", "-4", "-brief", "addr", "show", "scope", "global"],
                text=True, timeout=3,
            )
            for line in out.splitlines():
                parts = line.strip().split()
                for p in parts:
                    if "/" in p and p[0].isdigit():
                        ip = p.split("/")[0]
                        if not ip.startswith("127."):
                            lan_ip = ip
                            break
                if lan_ip:
                    break
        except Exception:
            pass

    # ── Classify gateway host ──────────────────────────────────
    import ipaddress as _ipaddr

    def _is_loopback(host: str) -> bool:
        return host in ("127.0.0.1", "localhost", "::1", "ip6-localhost")

    def _is_private(host: str) -> bool:
        try:
            return _ipaddr.ip_address(host).is_private
        except ValueError:
            return False

    if _is_loopback(gateway_host):
        return "127.0.0.1"

    if lan_ip and gateway_host == lan_ip:
        return lan_ip  # same machine via LAN

    if _is_private(gateway_host):
        if lan_ip:
            return lan_ip
        return "127.0.0.1"

    # ── Hostname (not IP): try DNS resolution ──
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as _dns:
            resolved = _dns.submit(
                socket.gethostbyname, gateway_host
            ).result(timeout=5)
        if _is_loopback(resolved):
            return "127.0.0.1"
        if lan_ip and resolved == lan_ip:
            return lan_ip
        if _is_private(resolved):
            return lan_ip if lan_ip else "127.0.0.1"
    except Exception:
        pass

    # ── Public IP: try external detection ──
    try:
        import urllib.request as _ur
        req = _ur.Request(
            "https://ifconfig.me", headers={"User-Agent": "curl/7.0"}
        )
        with _ur.urlopen(req, timeout=5) as resp:
            external_ip = resp.read().decode().strip()
            if external_ip and not _is_private(external_ip):
                logger.info(
                    "[amail_setup] Detected external IP %s for webhook callback "
                    "(gateway at %s is public)", external_ip, gateway_host
                )
                return external_ip
    except Exception:
        pass

    if lan_ip:
        logger.warning(
            "[amail_setup] Gateway at %s is public but cannot detect external IP. "
            "Using LAN IP %s — gateway must be able to reach this address. "
            "Set AMAIL_WEBHOOK_HOST to override.", gateway_host, lan_ip
        )
        return lan_ip

    return "127.0.0.1"


# ═══════════════════════════════════════════════════════════════
# Gateway config persistence
# ═══════════════════════════════════════════════════════════════

def _save_gateway_config(
    gateway_url: str,
    admin_key: str,
    system_id: str,
    domain: str = "",
    system_name: str = "",
    save_raw_snapshots: bool = False,
    manager_address: str = "",
    webhook_host: str = "",
) -> None:
    """Save amail gateway connection config to standalone JSON file.

    Writes to ~/.agentmail/{system_id}/amail_gateway.json — clean separation.
    """
    cfg = {
        "gateway_url": gateway_url,
        "admin_key": admin_key,
        "system_id": system_id,
        "system_name": system_name,
        "save_raw_snapshots": save_raw_snapshots,
    }
    if domain:
        cfg["domain"] = domain
    if manager_address:
        cfg["manager_address"] = manager_address
    if webhook_host:
        cfg["webhook_host"] = webhook_host

    gateway_path = _gateway_config_path(system_id)
    gateway_path.parent.mkdir(parents=True, exist_ok=True)
    with open(gateway_path, "w") as f:
        json.dump(cfg, f, indent=2)


# ═══════════════════════════════════════════════════════════════
# System initialization (product code path)
# ═══════════════════════════════════════════════════════════════

def init_system(
    product_code: str,
    system_id: str,
    system_name: str,
    domain: str = "",
    gateway_url: str = "",
    save_raw_snapshots: bool = False,
    manager_address: str = "",
    webhook_host: str = "",
) -> dict:
    """Initialize a system using a product activation code.

    This is the first-step setup for a new system that has NOT been activated
    yet.  It takes a pre-generated product activation code, activates it on
    the server, creates the system + default domain + quotas, and returns a
    system_admin API key.

    The returned admin_key is saved to the global Hermes config automatically.
    """
    # Resolve gateway_url from config/env if not provided
    if not gateway_url:
        cfg = _load_gateway_config()
        gateway_url = cfg.get("gateway_url", "") if cfg else ""
    if not gateway_url:
        return {
            "success": False,
            "error": "gateway_url is required (pass it or set AMAIL_GATEWAY_URL)",
        }

    if not product_code:
        return {
            "success": False,
            "error": "product_code is required for system initialization",
        }

    # Backend auto-generates system_id/system_name/domain
    client = _GatewayClient(gateway_url, "")
    result = client.activate_system(
        code=product_code,
        system_name=system_name or None,
        domain=domain or None,
    )

    status = result.get("status", 0)
    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", f"Activation failed (HTTP {status})"),
            "status": status,
        }

    admin_key = result.get("raw_key", "")
    created_system_id = result.get("system_id", system_id)
    created_domain = result.get("domain", domain)

    if not admin_key:
        return {
            "success": False,
            "error": "No admin_key returned from server",
            "status": status,
        }

    _save_gateway_config(
        gateway_url=gateway_url,
        admin_key=admin_key,
        system_id=created_system_id,
        domain=created_domain,
        system_name=system_name or result.get("system_name", ""),
        save_raw_snapshots=save_raw_snapshots,
        manager_address=manager_address,
        webhook_host=webhook_host,
    )
    logger.info("[amail_setup] Gateway config saved to %s", _gateway_config_path())

    return {
        "success": True,
        "system_id": created_system_id,
        "admin_key": admin_key,
        "gateway_url": gateway_url,
        "domain": created_domain,
        "system_name": system_name or result.get("system_name", ""),
    }


# ═══════════════════════════════════════════════════════════════
# Unified setup entry point
# ═══════════════════════════════════════════════════════════════

def setup(
    gateway_url: str,
    system_id: str,
    admin_key: str = "",
    product_code: str = "",
    system_name: str = "",
    domain: str = "",
    save_raw_snapshots: bool = False,
    manager_address: str = "",
    webhook_host: str = "",
    webhook_base_url: str = "",
    webhook_secret: str = "",
) -> dict:
    """Unified integration entry point.

    Provide gateway_url + system_id + ONE of (admin_key, product_code).
    The function auto-detects the path and saves config.

    Args:
        gateway_url:         amail gateway server URL (required)
        system_id:           System identifier
        admin_key:           Existing system_admin API key
        product_code:        Product activation code (one-time; creates system if new)
        system_name:         Human-readable name (only used with product_code path)
        domain:              Default mail domain (optional)
        save_raw_snapshots:  Persist raw email snapshots to disk (default: False)
        manager_address:     Default manager email
        webhook_host:        Bridge/webhook callback address
        webhook_base_url:    Default webhook URL for inbound routing (optional)
        webhook_secret:      HMAC secret for webhook verification (optional)

    Returns:
        {"success": True, "system_id": "...", "path": "admin_key"|"activation", ...}
        {"success": False, "error": "..."}
    """
    if not gateway_url:
        return {"success": False, "error": "gateway_url is required"}

    # Auto-detect webhook callback host
    if not webhook_host:
        webhook_host = os.environ.get("AMAIL_WEBHOOK_HOST", "")
    if not webhook_host:
        webhook_host = _detect_webhook_host(gateway_url)

    # ── Path A: admin_key provided (already-activated system) ──
    if admin_key:
        if not system_id:
            return {
                "success": False,
                "error": "system_id is required for admin_key path",
            }
        _save_gateway_config(
            gateway_url=gateway_url,
            admin_key=admin_key,
            system_id=system_id,
            domain=domain or "admin.local",
            system_name=system_name,
            save_raw_snapshots=save_raw_snapshots,
            manager_address=manager_address,
            webhook_host=webhook_host,
        )
        return {
            "success": True,
            "system_id": system_id,
            "path": "admin_key",
            "note": "Admin key saved. Agent keys can now be created via POST /api/v1/api-keys.",
        }

    # ── Path B: product_code provided (new system activation) ──
    if product_code:
        result = init_system(
            product_code=product_code,
            system_id=system_id,
            system_name=system_name,
            domain=domain,
            gateway_url=gateway_url,
            save_raw_snapshots=save_raw_snapshots,
            manager_address=manager_address,
            webhook_host=webhook_host,
        )
        if result.get("success"):
            result["path"] = "activation"
        return result

    return {
        "success": False,
        "error": "Either admin_key or product_code is required",
    }
