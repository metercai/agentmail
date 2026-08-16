#!/usr/bin/env python3
"""ensure_webhook_config.py — 幂等确保 Hermes profile 的 webhook 入站配置就位。

安装断链根因(2026-08-16 多次): 安装链(install-tools.sh / configure.sh /
register_profiles.py)从未写以下配置,全部靠手工补——缺任一项即断链:
  1. profile config.yaml `platform_toolsets.webhook` 缺 `agentmail`
     → webhook 会话回退默认工具集(hermes-webhook,无 send_mail),
     agent 物理上无法回邮件("收得到回不出")
  2. profile config.yaml `platforms.webhook.enabled` 缺失
     → 注册链 _ensure_profile_webhook 读不到,webhook_url 为空
  3. webhook_subscriptions.json 缺路由 `agentmail-inbound`
     → 注册链 _ensure_webhook_route 本应创建,但仅在注册执行时;
     缺路由 → 入站 webhook 404
  4. webhook_subscriptions.json 缺路由 `amail-inbound`
     → bridge 转发路径硬编码 /webhooks/amail-inbound(router.rs:43),
     缺此路由名 → bridge 转发 404,邮件卡 pending 无限重试

本脚本幂等: 已存在的配置项保留(尤其 secret——变更会致 bridge 转发
HMAC 401);只补缺失项。被 configure.sh(安装)与独立运维共同调用。

用法:
  ensure_webhook_config.py --profile-dir ~/.hermes/profiles/agentmail
"""
import argparse
import json
import secrets
import sys
import time
from pathlib import Path

# tools/ 是共享模块根(仓库内与拷贝树都可用)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools" / "hermes"))

# 路由名:agentmail-inbound = Hermes 自身入站;amail-inbound = bridge
# 转发目标(bridge router.rs 硬编码 /webhooks/amail-inbound)
REQUIRED_ROUTES = ["agentmail-inbound", "amail-inbound"]
WEBHOOK_TOOLSET = ["agentmail", "web", "file", "terminal", "search", "delegation"]


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _dump_yaml(path: Path, data: dict) -> None:
    import yaml
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    tmp.replace(path)


def ensure_profile_config(profile_dir: Path) -> list:
    """确保 platforms.webhook.enabled + platform_toolsets.webhook 含 agentmail。"""
    changes = []
    cfg_path = profile_dir / "config.yaml"
    if not cfg_path.exists():
        changes.append(f"config.yaml missing ({cfg_path}) — skipped")
        return changes

    cfg = _load_yaml(cfg_path)
    dirty = False

    # 1) platforms.webhook.enabled(注册链 _ensure_profile_webhook 依赖)
    platforms = cfg.get("platforms") or {}
    wh = platforms.get("webhook") or {}
    if not wh.get("enabled"):
        # 复用已有端口/secret,缺则生成——与 _ensure_profile_webhook 同构
        port = wh.get("port") or wh.get("extra", {}).get("port") or 8644
        secret = wh.get("extra", {}).get("secret") or secrets.token_hex(32)
        platforms["webhook"] = {
            "enabled": True,
            "host": "0.0.0.0",
            "port": port,
            "extra": {"port": port, "secret": secret},
        }
        cfg["platforms"] = platforms
        changes.append(f"platforms.webhook enabled (port={port})")
        dirty = True

    # 2) platform_toolsets.webhook 含 agentmail(webhook 会话工具能力)
    pt = cfg.get("platform_toolsets") or {}
    wh_tools = pt.get("webhook") or []
    if not isinstance(wh_tools, list):
        wh_tools = []
    if "agentmail" not in wh_tools:
        # 缺 → 用完整默认工具集(用户批准);空/旧值只补 agentmail 不动其他
        if not wh_tools:
            wh_tools = list(WEBHOOK_TOOLSET)
        else:
            wh_tools.append("agentmail")
        pt["webhook"] = wh_tools
        cfg["platform_toolsets"] = pt
        changes.append(f"platform_toolsets.webhook -> {wh_tools}")
        dirty = True

    if dirty:
        _dump_yaml(cfg_path, cfg)
    return changes


def ensure_routes(profile_dir: Path) -> list:
    """确保 webhook_subscriptions.json 两条路由存在(skills=['agentmail'])。"""
    changes = []
    subs_path = profile_dir / "webhook_subscriptions.json"
    subs = {}
    if subs_path.exists():
        try:
            subs = json.loads(subs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if not isinstance(subs, dict):
        subs = {}

    # 路由 secret 与 platforms.webhook.extra.secret 保持一致(已有路由的
    # secret 不覆盖——bridge 转发验签依赖它与云端一致)
    cfg = _load_yaml(profile_dir / "config.yaml")
    route_secret = (cfg.get("platforms", {}).get("webhook", {})
                    .get("extra", {}).get("secret", ""))
    if not route_secret and subs.get(REQUIRED_ROUTES[0]):
        route_secret = subs[REQUIRED_ROUTES[0]].get("secret", "")
    if not route_secret:
        route_secret = secrets.token_hex(32)

    for name in REQUIRED_ROUTES:
        if name in subs:
            # 已存在:确保 skills/preprocess 正确(secret 不动)
            entry = subs[name]
            if entry.get("skills") != ["agentmail"]:
                entry["skills"] = ["agentmail"]
                changes.append(f"route {name} skills fixed")
            if entry.get("preprocess") != "agentmail_gateway":
                entry["preprocess"] = "agentmail_gateway"
                changes.append(f"route {name} preprocess fixed")
            continue
        subs[name] = {
            "description": f"agentmail inbound email route ({name})",
            "events": [],
            "secret": route_secret,
            "preprocess": "agentmail_gateway",
            "prompt": "",
            "skills": ["agentmail"],
            "deliver": "log",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        changes.append(f"route {name} created")

    if changes:
        subs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = subs_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(subs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(subs_path)
    return changes


def is_amail_profile(profile_dir: Path) -> bool:
    """判断 profile 是否 amail 相关:有 .agentmail 指针,或已有
    amail 配置痕迹(platform_toolsets 含 agentmail / platforms.webhook
    preprocess=agentmail_gateway / 已有两条路由之一)。无关 profile
    (erp/qlbio 等)绝不写入——避免污染非 amail 目录。"""
    if (profile_dir / ".agentmail").is_file():
        return True
    cfg = _load_yaml(profile_dir / "config.yaml")
    pt = cfg.get("platform_toolsets") or {}
    wh_tools = pt.get("webhook") or []
    if "agentmail" in (wh_tools if isinstance(wh_tools, list) else []):
        return True
    wh = (cfg.get("platforms") or {}).get("webhook") or {}
    if wh.get("extra", {}).get("secret"):
        # 有 webhook secret 但无 agentmail 标记 → 保守:看路由
        subs_path = profile_dir / "webhook_subscriptions.json"
        if subs_path.exists():
            try:
                subs = json.loads(subs_path.read_text(encoding="utf-8"))
                if isinstance(subs, dict) and any(
                        r in subs for r in REQUIRED_ROUTES):
                    return True
            except Exception:
                pass
        return False
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile-dir", help="单个 Hermes profile 目录(显式指定=强制处理)")
    ap.add_argument("--profiles-dir", default="",
                    help="Hermes profiles 根目录(批量,仅处理有 amail 标记的 profile)")
    args = ap.parse_args()

    if args.profile_dir:
        profile_dirs = [Path(args.profile_dir).expanduser()]
    elif args.profiles_dir:
        root = Path(args.profiles_dir).expanduser()
        profile_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    else:
        print("✗ 需 --profile-dir 或 --profiles-dir")
        return 1

    total_changes = 0
    for pd in profile_dirs:
        if not pd.is_dir():
            print(f"✗ profile dir not found: {pd}")
            continue
        # 批量模式只处理 amail 标记 profile(--profile-dir 显式指定不受限,
        # 但调用方须自知目标);无关 profile 绝不写入,防污染。
        if args.profiles_dir and not is_amail_profile(pd):
            continue
        changes = ensure_profile_config(pd) + ensure_routes(pd)
        if changes:
            total_changes += len(changes)
            print(f"ensure_webhook_config [{pd.name}]:")
            for c in changes:
                print(f"  • {c}")
    if total_changes == 0:
        print("ensure_webhook_config: all present (no changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
