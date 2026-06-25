#!/usr/bin/env python3
"""Call setup() with environment variables. Used by integrate.sh Step 5."""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib"))
from setup import setup

kwargs = dict(
    gateway_url=os.environ.get("INTEGRATE_GATEWAY_URL", ""),
    system_id=os.environ.get("INTEGRATE_SYSTEM_ID", ""),
    domain=os.environ.get("INTEGRATE_AMAIL_DOMAIN", "") or "",
    save_raw_snapshots=os.environ.get("INTEGRATE_SAVE_SNAPSHOTS", "false") == "true",
    manager_address=os.environ.get("INTEGRATE_MANAGER_ADDRESS", "") or "",
    webhook_host=os.environ.get("INTEGRATE_WEBHOOK_HOST", "") or "",
    system_name=os.environ.get("INTEGRATE_SYSTEM_NAME", "") or "",
)
if os.environ.get("INTEGRATE_USE_PRODUCT_CODE", "") == "true":
    kwargs["product_code"] = os.environ.get("INTEGRATE_PRODUCT_CODE", "")
else:
    kwargs["admin_key"] = os.environ.get("INTEGRATE_ADMIN_KEY", "")
result = setup(**kwargs)
display = {k: v for k, v in result.items() if k not in ("success", "path")}
print(json.dumps(display, indent=2, ensure_ascii=False))
if not result.get("success"):
    err = result.get("error") or result.get("detail") or "Unknown error"
    print(f"__ERROR__:{err}")
    sys.exit(1)
