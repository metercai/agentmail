"""Core integration steps — shared domain activation, profile registration.
Replaces complex shell logic to avoid quoting/heredoc bugs."""
import sys, os, json, re, time, hashlib, urllib.request, urllib.error

# ── System name validation ────────────────────────────────────────
SYSNAME_RE = re.compile(r'^[a-z][a-z0-9_-]{2,7}$')

def validate_sysname(name: str) -> str:
    name = name.strip().lower()
    if not SYSNAME_RE.match(name):
        print("Must be lowercase letter + 2-7 more chars (a-z, 0-9, -, _)", file=sys.stderr)
        sys.exit(1)
    return name

# ── Activation prompt (loop with retry) ──────────────────────────
SYSTEM_NAME = ""

def prompt_activate(gateway_url: str, product_code: str) -> dict:
    """Interactive activation loop. Returns {system_id, admin_key, domain, system_name}"""
    global SYSTEM_NAME
    print("  Email format: profile.SYS_NAME@shared.domain", file=sys.stderr)
    while True:
        sys.stderr.write("  System identifier (3-8 chars, [a-z0-9_-]): ")
        sys.stderr.flush()
        raw = input().strip()
        try:
            name = validate_sysname(raw)
        except SystemExit:
            continue

        data = json.dumps({"code": product_code, "system_name": name}).encode()
        req = urllib.request.Request(
            f"{gateway_url.rstrip('/')}/api/v1/activate-system",
            data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            body = json.loads(resp.read())
            SYSTEM_NAME = body.get("system_name", name)
            print(f"  System activated:", file=sys.stderr)
            print(f"  ├─ system_id:  {body.get('system_id','')}", file=sys.stderr)
            print(f"  ├─ domain:     {body.get('domain','')}", file=sys.stderr)
            print(f"  └─ identifier: {SYSTEM_NAME}", file=sys.stderr)
            return {
                "system_id": body.get("system_id", ""),
                "admin_key": body.get("raw_key", ""),
                "domain": body.get("domain", ""),
                "system_name": SYSTEM_NAME,
            }
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            error, detail = body.get("error", ""), body.get("detail", "")
            if e.code == 410:
                print(f"  Activation code already claimed — use a fresh code", file=sys.stderr)
                sys.exit(1)
            elif e.code == 409:
                print(f"  Identifier '{name}' is already taken — choose another", file=sys.stderr)
            elif e.code == 429:
                m = re.search(r'(\d+)', detail)
                wait = max(int(m.group(1)) if m else 5, 1)
                print(f"  Rate limited — retry after {wait}s", file=sys.stderr)
                # User reads the message and decides when to retry
            else:
                print(f"  {detail or error}", file=sys.stderr)
                print(f"  Please try a different name or check the code", file=sys.stderr)

if __name__ == "__main__":
    import sys
    gw = os.environ.get("GATEWAY_URL", "")
    code = os.environ.get("PRODUCT_CODE", "")
    if not gw or not code:
        print("GATEWAY_URL and PRODUCT_CODE env vars required", file=sys.stderr)
        sys.exit(1)
    result = prompt_activate(gw, code)
    if result.get("system_id"):
        # Export results for the shell script
        print(f"::set-system-id::{result['system_id']}")
        print(f"::set-admin-key::{result['admin_key']}")
        print(f"::set-domain::{result['domain']}")
        print(f"::set-system-name::{result['system_name']}")
    else:
        sys.exit(1)
