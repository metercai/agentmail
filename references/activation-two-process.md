# Activation Code — Two-Process Separation

## Principle

NEVER call `generate_address_codes` and `activate_address` in the same process.
The admin process that creates the code must NOT see the raw API key.

The system uses **two separate activation code types** with different lifecycles:

| Level | Code Type | Creator | Activator | Creates |
|-------|-----------|---------|-----------|---------|
| 1 | `product` | Platform Admin | Tenant Admin (or user) | Tenant + tenant_admin key |
| 2 | `address` | Tenant Admin | Agent Process | Agent API key |

## Level 1: Product Activation — Tenant Init

### Admin Process (Platform Admin creates inventory)

```bash
# Platform admin pre-generates product codes via API
POST /api/v1/admin/activation-codes/batch
X-Api-Key: sk-admin-...

{
  "code_type": "product",
  "product_id": "pro-basic",
  "count": 10
}
# → Returns raw_codes (shown once, must be distributed out-of-band)
```

### User Process (runs `integrate.sh` or `init_tenant()`)

```python
# amail_tools.py — init_tenant()
client = _GatewayClient(gateway_url, "")  # No auth — code is credential

result = client.activate_tenant(
    code=product_code,
    tenant_id="my-team",
    tenant_name="My Team",
)
# → Backend returns: {"raw_key": "sk-tenant-admin-xxxx", ...}
# Client reads: result.get("raw_key")

admin_key = result.get("raw_key")
# Save to Hermes global config automatically
```

**IMPORTANT**: Backend returns `raw_key` (not `admin_key`).

## Level 2: Address Activation — Agent Provisioning

### Admin Process (TenantAdmin context — profile creation hook)

```python
# amail_tools.py — _auto_register_email()
client = _GatewayClient(config["gateway_url"], config["admin_key"])  # tenant_admin scope

# Step 1: Generate address activation code (NOT an API key directly)
code_result = client.generate_address_codes(
    tenant_id=tenant_id,
    domain=config["domain"],
    count=1,
    email_address=email,
)
activation_code = code_result["raw_codes"][0]

# Step 2: Write code to profile config. NO api_key in config.
_inject_profile_config(profile_dir, {
    "email": email,
    "activation_code": activation_code,
    "gateway_url": config["gateway_url"],
    "domain": config["domain"],
    "tenant_id": tenant_id,
})
# Profile config at this point:
#   { activation_code: "addr-xxxx-...", no api_key }
```

### Agent Process (Agent context, separate startup)

```python
# amail_tools.py — _auto_activate_profile()
config_path = Path(profile_dir) / "amail.json"
prof = json.load(open(config_path))

activation_code = prof.get("activation_code", "")
if not activation_code:
    return  # Already activated

if prof.get("api_key"):
    # Already has a key — just clean up stale activation_code
    prof.pop("activation_code", None)
    json.dump(prof, open(config_path, "w"))
    return

# Activate using a client with NO api_key (unauthenticated endpoint)
client = _GatewayClient(config.get("gateway_url", prof.get("gateway_url")), "")
result = client.activate_address(
    code=activation_code,
    email_address=prof.get("email", ""),
)

if result.get("success"):
    prof["api_key"] = result["raw_key"]
    prof.pop("activation_code", None)
    json.dump(prof, open(config_path, "w"))
    # Profile config now:
    #   { api_key: "sk-...", no activation_code }
```

**IMPORTANT**: 
- Uses `POST /api/v1/activate-address` (NEW endpoint), NOT `POST /api/v1/activate` (OLD endpoint)
- Requires `email_address` in the request body
- The code is sent without auth — the activation code IS the credential

## Why Two Processes?

- **Admin process** runs as TenantAdmin/SystemAdmin. If it saw the raw_key,
  the admin could use it to impersonate the agent.
- **Agent process** runs as the agent itself (or an automated systemd service).
  Only the agent should possess its own credentials.
- The `activation_code` is a one-time bearer token. It replaces the insecure
  "admin creates key and shares it" pattern.

## Flow Summary

```
Platform Admin pre-generates product codes (inventory)
    ↓ distribute product code out-of-band
User activates tenant with product code → gets tenant_admin key
    ↓
Tenant Admin runs profile creation hook:
    generate_address_codes() → writes activation_code to profile config
    ↓ (agent process starts)
Agent auto-activates: activate_address(code, email_address)
    → config now has api_key, activation_code removed
```
