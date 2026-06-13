# integrate.sh Code Review Report

## Critical

### 1. $DOMAIN undefined in API key creation (line 693)

```bash
-d '{"system_id":"'"$SYSTEM_ID"'","email_address":"'"$DOMAIN"'","scopes":...
```

`$DOMAIN` is never defined. Should be `$AMAIL_DOMAIN`. The sed fix at line 686 missed this occurrence.
Result: empty email_address → gateway returns 400 Bad Request → domain admin key creation silently fails.

### 2. $WEBHOOK_MODE unset in AUTO_MODE (Step 4)

In AUTO_MODE (line 538-545), only SAVE_SNAPSHOTS, MANAGER_ADDRESS, and WEBHOOK_HOST are read from env. WEBHOOK_MODE is NOT set. When Step 5a runs (line 719), `$WEBHOOK_MODE` is either empty string or carries a stale value.

Fix: AUTO_MODE branch should also set WEBHOOK_MODE from AMAIL_WEBHOOK_MODE env var, or default to something sensible.

### 3. $ADMIN_KEY in process arguments

```bash
curl ... -H "X-Api-Key: $ADMIN_KEY"
```

Admin key appears in `ps aux` output. Use `--header @-` with stdin, or set via environment:

```bash
export AMAIL_KEY="$ADMIN_KEY"
curl ... -H "X-Api-Key: $AMAIL_KEY"  # still visible, but env var
```

Actually, `curl` with `-H` passes the header value in the process command line. This is a pre-existing issue across the entire script.

## Medium

### 4. Bridge binary download without verification (line 728)

`curl -sL ... | tar xz` — no SHA256 checksum verification. Supply chain risk: if GitHub release is compromised, attacker's binary runs as the user. Add SHA256 check.

### 5. Fragile TOML manipulation (line 796)

`cfg.replace("[pull]", "[pull]\napi_key = ...")` — breaks if `[pull]` has leading/trailing whitespace or comments. Use Python `toml` module instead.

### 6. product_code path: empty domain still fatal (line 528)

Admin_key path just warns (`step_ok "Domain not set"`). Product_code path: `step_fail "Domain is required"`. Inconsistent — should also allow continuing without domain.

## Low

### 7. idempotency edge case: domain admin key already exists

If `integrate.sh` is re-run after domain admin key creation succeeded, Step 5a calls `POST /api/v1/api-keys` again. The `UNIQUE(system_id, domain_addr)` constraint causes 409/400. The script should check if a domain admin key already exists before creating one.

### 8. `set -eo pipefail` combined with `|| true`

`set -e` is active but `|| true` patterns suppress failures. Intentional for curl failures, but could mask real errors. Review each `|| true` for necessity.
