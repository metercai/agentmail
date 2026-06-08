# Two-Level Activation Code Flow

## Architecture Overview

```
Platform Admin                    Tenant Admin                      Agent Process
      │                                │                                    │
      │  1. Generate product codes     │                                    │
      ├────POST /activation-codes/     │                                    │
      │     batch (code_type=product)  │                                    │
      │                                │                                    │
      │  2. Distribute product code    │                                    │
      ├───────────────────────────────>│                                    │
      │                                │                                    │
      │  3. Activate tenant            │                                    │
      │  POST /activate-tenant         │                                    │
      │  {code, tenant_id, ...}        │                                    │
      │  → returns tenant_admin key    │                                    │
      │    (raw_key, NOT admin_key)    │                                    │
      │                                │                                    │
      │                                │  4. Generate address codes         │
      │                                │  POST /activation-codes/batch      │
      │                                │  (code_type=address)               │
      │                                │  → returns raw_codes               │
      │                                │                                    │
      │                                │  5. Write address code to          │
      │                                │     profile config                 │
      │                                ├───────────────────────────────────>│
      │                                │                                    │
      │                                │  6. Agent startup:                 │
      │                                │  POST /activate-address            │
      │                                │  {code, email_address, scopes}     │
      │                                │  → returns agent api_key           │
      │                                │                                    │
```

## Level 1: Product Activation (Platform → Tenant)

### Generate Product Codes (Platform Admin only)

```bash
POST /api/v1/admin/activation-codes/batch
X-Api-Key: sk-admin-...     # ← platform admin key (NOT available to tenants)

{
  "code_type": "product",
  "product_id": "pro-basic",
  "count": 10,
  "expires_in_mins": 10080
}

→ {
    "status": "created",
    "code_type": "product",
    "product_id": "pro-basic",
    "count": 10,
    "raw_codes": ["pro-basi-a1b2-c3d4-..."]
  }
```

> **Security**: The platform admin key is never exposed to tenant admins.
> Product codes are pre-generated inventory, distributed out-of-band.

### Activate Tenant (Unauthenticated — code is the credential)

```bash
POST /api/v1/activate-tenant
(no auth — code is credential)

{
  "code": "pro-basi-a1b2-c3d4-...",
  "tenant_id": "my-team",
  "tenant_name": "My Team",
  "domain": "myteam.amrelay.io",          // optional, defaults to {tenant_id}.amrelay.io
  "webhook_url": "http://gateway:8080/webhooks",  // optional
  "webhook_secret": "hmac-secret"                 // optional
}

→ {
    "status": "activated",
    "raw_key": "sk-tenant-admin-xxxx",      # ← field name is "raw_key", not "admin_key"
    "tenant_id": "my-team",
    "tenant_name": "My Team",
    "domain": "myteam.amrelay.io"
  }
```

**Client code checks**: `result.get("raw_key")` — NOT `result.get("admin_key")`.

### What this creates:
- Tenant record with webhook_url + webhook_secret
- Default domain (`{tenant_id}.amrelay.io` or custom)
- Tenant quota (from product definition)
- tenant_admin API key (email_address = "")

### init_tenant() function (Python client)

```python
from amail_tools import init_tenant

result = init_tenant(
    product_code="pro-basi-a1b2-c3d4-...",
    tenant_id="my-team",
    tenant_name="My Team",
    relay_url="http://localhost:38080",
)
# → {"success": True, "tenant_id": "my-team", "admin_key": "sk-tenant-admin-xxxx", ...}
```

The returned `admin_key` is automatically saved to Hermes global config.

### Flow A: Existing Tenant (Direct Admin Key)

If you already have a tenant and a tenant_admin key, skip product code activation:

```bash
# Just set the config directly
bash integrate.sh
# Select mode 2 → provide tenant_id + admin_key
```

```python
# Or set env vars
export AMAIL_URL=http://localhost:38080
export AMAIL_ADMIN_KEY=sk-tenant-admin-xxxx
export AMAIL_TENANT_ID=my-team
export AMAIL_DOMAIN=myteam.amrelay.io
```

---

## Level 2: Address Activation (Tenant → Agent)

### Prerequisites
- Tenant must already exist (activated via Level 1 or pre-existing)
- You have the tenant_admin key

### List Available Address Codes (Tenant Admin)

```bash
GET /api/v1/admin/activation-codes?code_type=address&claimed=false
X-Api-Key: sk-tenant-admin-xxxx

→ {
    "codes": [
      {
        "id": 1,
        "code_prefix": "myteam-a1b2-c3d4-...",
        "claimed": false,
        "code_type": "address",
        "tenant_id": "my-team",
        "domain": "myteam.amrelay.io",
        "email_address": null,
        ...
      }
    ],
    "count": 1
  }
```

### Generate Address Codes (Tenant Admin, if none available)

```bash
POST /api/v1/admin/activation-codes/batch
X-Api-Key: sk-tenant-admin-xxxx

{
  "code_type": "address",
  "tenant_id": "my-team",
  "domain": "myteam.amrelay.io",
  "email_address": "agent-1@myteam.amrelay.io",  // optional, pre-bind to address
  "count": 1,
  "expires_in_mins": 10080
}

→ {
    "status": "created",
    "code_type": "address",
    "tenant_id": "my-team",
    "domain": "myteam.amrelay.io",
    "count": 1,
    "raw_codes": ["myteam-a1b2-c3d4-..."]
  }
```

### Activate Address (Unauthenticated — Agent Process)

```bash
POST /api/v1/activate-address
(no auth — code is credential)

{
  "code": "myteam-a1b2-c3d4-...",
  "email_address": "agent-1@myteam.amrelay.io",
  "scopes": ["send"]
}

→ {
    "status": "activated",
    "raw_key": "sk-agent-xxxx",
    "email_address": "agent-1@myteam.amrelay.io",
    "tenant_id": "my-team",
    "scopes": ["send"]
  }
```

> **IMPORTANT**: The agent process calls `POST /api/v1/activate-address`, NOT `POST /api/v1/activate`.
> The old `/api/v1/activate` endpoint uses the legacy `pending_keys` table.
> The new `/api/v1/activate-address` uses the `activation_codes` table.

### What this creates:
- Email route for the address (domain record auto-created if missing)
- Agent-scoped API key with `email_address = address`
- Activation code marked as claimed

### Client Code

```python
from amail_tools import _RelayClient

# Tenant admin generates address codes
client = _RelayClient("http://localhost:38080", "sk-tenant-admin-xxxx")
result = client.list_address_codes(tenant_id="my-team")
if not result.get("codes"):
    result = client.generate_address_codes(
        tenant_id="my-team",
        domain="myteam.amrelay.io",
        count=1,
        email_address="agent-1@myteam.amrelay.io",
    )
    activation_code = result["raw_codes"][0]

# Write to profile config (BEFORE activation — contains activation_code, not api_key)
profile_config = {
    "email": "agent-1@myteam.amrelay.io",
    "activation_code": activation_code,  # ← NOT the api_key!
    "relay_url": "http://localhost:38080",
    "tenant_id": "my-team",
    "domain": "myteam.amrelay.io",
}

# Agent process activates on startup
agent_client = _RelayClient("http://localhost:38080", "")  # no auth
activate_result = agent_client.activate_address(
    code=activation_code,
    email_address="agent-1@myteam.amrelay.io",
)
print(activate_result)
# → {"success": True, "raw_key": "sk-agent-xxxx", "api_key_id": 0, ...}
```

---

## Config Lifecycle

### Global Config (config.yaml) — Tenant Level

**Before initialization (new tenant):**
```yaml
platforms:
  amail:
    relay_url: http://localhost:38080
    product_code: pro-basi-a1b2-c3d4-...
```

**After tenant activation (new tenant) or direct config (existing tenant):**
```yaml
platforms:
  amail:
    relay_url: http://localhost:38080
    admin_key: sk-tenant-admin-xxxx
    tenant_id: my-team
    domain: myteam.amrelay.io
```

### Profile Config (amail.json) — Agent Level

**Before agent activation:**
```json
{
  "email": "agent-1@myteam.amrelay.io",
  "activation_code": "myteam-a1b2-c3d4-...",
  "relay_url": "http://localhost:38080",
  "tenant_id": "my-team",
  "domain": "myteam.amrelay.io"
}
```

**After agent activation:**
```json
{
  "email": "agent-1@myteam.amrelay.io",
  "api_key": "sk-agent-xxxx",
  "api_key_id": 123,
  "relay_url": "http://localhost:38080",
  "tenant_id": "my-team",
  "domain": "myteam.amrelay.io"
}
```

The activation_code field is removed and replaced with api_key when the agent activates.

---

## `_RelayClient` Methods

| Method | Auth | Scope | Purpose |
|--------|------|-------|---------|
| `activate_tenant(code, tenant_id, tenant_name, ...)` | none | — | Level 1: Product → Tenant |
| `list_address_codes(tenant_id, claimed)` | X-Api-Key | tenant_admin | Query available address codes |
| `generate_address_codes(tenant_id, domain, count, ...)` | X-Api-Key | tenant_admin | Create address codes |
| `activate_address(code, email_address, scopes=...)` | none | — | Level 2: Address → Agent key |
| `register_email(tenant_id, mx_domain, email, webhook_url, ...)` | X-Api-Key | tenant_admin | Register email route |
| `_request_unauth(method, path, body)` | none | — | Unauthenticated HTTP helper |

## Key Differences from Legacy Flow

| Aspect | Legacy (Direct API Key) | New (Two-Level Activation) |
|--------|------------------------|---------------------------|
| Tenant creation | Admin API call (requires platform admin key) | Product code activation (no auth) |
| Admin key source | Bootstrap one-time print (platform admin key) | Returned from tenant activation (`raw_key`) |
| Agent key creation | Admin calls create_api_key() → sees raw_key | Address code → agent self-activates (creator never sees raw_key) |
| Creator sees raw_key? | YES (admin sees agent key) | NO (separate processes) |
| Profile config | Contains api_key immediately | Contains activation_code → auto-updates on first use |
| Quota management | Manual per-tenant | Auto from product definition |
| Address activation endpoint | `POST /api/v1/activate` (pending_keys table) | `POST /api/v1/activate-address` (activation_codes table) |
| Tenant activation response field | N/A | `raw_key` (not `admin_key`) |
