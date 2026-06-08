# Installing amail Tools as Hermes Built-in Tools

This guide covers how to install the 6 amail tools (`send_mail`, `contact_profile`,
`set_contact_profile`, `manage_contacts`, `email_summary`, `set_email_summary`)
so they appear in every Hermes session and can be called from SKILL files.

---

## Quick Install (one command)

```bash
bash /home/ubuntu/agent-mail-relay/integrations/hermes/install-tools.sh
```

This script:
1. Copies `tools/amail_tools.py` into the Hermes source tree
2. Adds the 6 tool names to `_HERMES_CORE_TOOLS`
3. Registers the `amail` toolset in `toolsets.py`

---

## Manual Install (4 steps)

### Step 1: Copy the tool file

```bash
cp /home/ubuntu/agent-mail-relay/integrations/hermes/tools/amail_tools.py \
   ~/.hermes/hermes-agent/tools/amail_tools.py
```

The file self-registers via `registry.register()` — no import hacks needed.
Hermes auto-discovers it at startup by scanning `tools/*.py`.

### Step 2: Edit `toolsets.py` — add tools to `_HERMES_CORE_TOOLS`

In `~/.hermes/hermes-agent/toolsets.py`, find the `_HERMES_CORE_TOOLS` list and
append these 6 names **before the closing `]`**:

```python
_HERMES_CORE_TOOLS = [
    # ... existing tools ...
    "send_mail", "manage_contacts",
    "contact_profile", "set_contact_profile",
    "email_summary", "set_email_summary",
]
```

### Step 3: Register the `amail` toolset (optional but recommended)

In the same file, find the `TOOLSETS` dict and add:

```python
TOOLSETS = {
    # ... existing toolsets ...
    "amail": {
        "description": "Agent email tools: send, contacts, contact profiles, and thread summaries via amail",
        "tools": [
            "send_mail", "manage_contacts",
            "contact_profile", "set_contact_profile",
            "email_summary", "set_email_summary",
        ],
        "includes": [],
    },
}
```

This makes the toolset show up in `hermes tools` and allows per-platform enable/disable.

### Step 4: Restart

```bash
hermes             # new session — tools auto-loaded
# or in-session:
/reset             # re-scans tools
```

Verify with:

```bash
hermes tools list | grep -E "send_mail|contact_profile|manage_contacts|email_summary"
```

---

## How the Tools Map to the SKILL Document

| SKILL Reference | Tool Name | Implementation |
|----------------|-----------|----------------|
| `send_mail(to, subject, body, ..., message_id)` | `send_mail` | `POST /api/v1/send`. `message_id` auto-resolves In-Reply-To + References via local `amail_messages.json` metadata store. |
| `contact_profile(address\|name)` | `contact_profile` | `GET /api/v1/admin/whitelists` |
| `set_contact_profile(address, profile)` | `set_contact_profile` | `PUT /api/v1/admin/whitelists/:id` with JSON merge |
| `manage_contacts(action, address, direction)` | `manage_contacts` | CRUD on `/api/v1/admin/whitelists` |
| `email_summary(message_id)` | `email_summary` | Local `amail_summaries.json`, keyed by thread_id resolved from message_id via metadata store |
| `set_email_summary(message_id, summary)` | `set_email_summary` | Same file, thread_id resolved internally from message_id |

### Key Design

- **`message_id` is the unified interface**: all tools accept `message_id`. No `thread_id` or `references` exposed to the agent.
- **Semantic API endpoints**: contacts and thread summaries use dedicated endpoints — no raw KV key names exposed to clients.
  - Contacts: `PUT/GET /api/v1/admin/contacts/:address`, `GET /api/v1/admin/contacts?name=...`
  - Thread summaries: `PUT/GET /api/v1/admin/thread-summary/:message_id`
  - Message metadata (internal): `PUT/GET /api/v1/admin/agent-state/msg:{mid}` — used by threading logic, not exposed to agents.
- **Storage in relay**: all state is stored in the relay's `agent_state` table (internal key format: `profile:{addr}`, `name:{name}`, `thread:{tid}`, `msg:{mid}`). Each agent's data is isolated by `api_key.email_address`. Clients should NOT use agent_state directly — use semantic endpoints instead.
- **Thread resolution**: `thread_id = references[0]` (root message), falls back to `message_id` itself.
- **Reply threading**: `send_mail(message_id=...)` internally looks up the original message's references from relay `msg:{mid}`, builds `In-Reply-To` + `References` headers, and stores the outbound message_id for future replies.
- **Email snapshots**: optional local storage. When `save_raw_snapshots: true`, the preprocessor saves snapshots to `raw_email/{agent_addr}/{yyyymm}/`.

### Storage

| Location | Key | Content |
|----------|-----|---------|
| Relay `agent_state` (internal) | `profile:{address}` | Contact profile JSON |
| Relay `agent_state` (internal) | `name:{name}` | `{"addresses": [...]}` index |
| Relay `agent_state` (internal) | `thread:{thread_id}` | Summary text |
| Relay `agent_state` (internal) | `msg:{message_id}` | `{"references": [...], "thread_id": "..."}` |
| Local (optional) | `raw_email/{agent_addr}/{yyyymm}/{mid}.json` | Raw email snapshot |

### Preprocessor Integration

```python
from amail_tools import store_inbound_message

store_inbound_message(
    message_id="<abc123@corp.com>",
    references=["<root@corp.com>", "<parent@corp.com>"],
    my_amail_addr="support.alice@project.com",         # for snapshot path isolation
    preprocessed_payload=preprocessed_json_dict,       # agent-visible JSON (after preprocess_mail_payload)
    attachment_sources={"report.pdf": "/tmp/..."},     # attachment files (optional)
)
```

## Configuration

The tool reads config from, in order of priority:

1. **Per-profile** `{profile_dir}/amail.json` — set automatically on profile creation
2. **Environment variables**: `AMAIL_URL`, `AMAIL_SYS_ID`, `AMAIL_MX_DOMAIN`
3. **Global Hermes config**: `~/.hermes/config.yaml` → `platforms.amail`

Minimal agent profile config (`{profile_dir}/amail.json`):

```json
{
  "relay_url": "http://localhost:38080",
  "api_key": "sk-...",
  "email": "agent@amail.example.com",
  "system_id": "admin",
  "domain": "amail.example.com"
}
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Tool not appearing in `hermes tools list` | Check `_HERMES_CORE_TOOLS` has the tool name; run `/reset` |
| "amail not configured" error | Set `AMAIL_URL` + `AMAIL_SYS_ID` env vars, or ensure `amail.json` exists |
| "address not in contacts" on `set_contact_profile` | Contact must exist first — use `manage_contacts(action="add", ...)` |
| Email send fails with 403 | Confirm API key has `send` scope. AgentAdmin keys can't send. |
| `email_summary` returns empty summary | No summary stored yet. Use `set_email_summary` first. |
