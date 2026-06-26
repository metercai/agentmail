# AgentMail

**Real-time, human-like email communication for AI agents — with humans or other agents.**

AgentMail wires [amail-gateway](https://github.com/metercai/amail-gateway) into
[Hermes Agent](https://github.com/nousresearch/hermes-agent), giving your AI
agent the ability to send and receive email through standard SMTP — no POP3/IMAP,
no polling, no mailbox configuration.

---

## Use Cases

- AI agents handling customer support via email
- Multi-agent collaboration over email threads
- Automated reporting and notification delivery
- Human-in-the-loop approval workflows
- Integration with existing email-based business processes
- Agent-to-agent (A2A) communication via SMTP

## Features

- **Zero-config inbound** — webhook-based, no polling, no IMAP
- **Standard SMTP outbound** — no proprietary API, works with any SMTP relay
- **End-to-end heartbeat** — built-in ping/pong test verifies the full pipeline
- **Persona support** — one agent profile, multiple email identities via persona prefix
- **Hook-based lifecycle** — auto-register/deregister on profile creation/deletion
- **Bilingual integration wizard** — interactive `integrate.sh` with EN/ZH support
- **Pipeline diagnostics** — `check_status.py` verifies all 4 layers in one command

## Quick Start

### Prerequisites

- [amail-gateway](https://github.com/metercai/amail-gateway) (running)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) (installed)
- [amail-bridge](https://github.com/metercai/amail-bridge) (auto-deployed by script)
- Python 3.10+

### One-command integration

```bash
git clone https://github.com/metercai/agentmail.git
cd agentmail
bash integrate.sh
```

The wizard guides you through:
1. Gateway connectivity check
2. Domain configuration (or activation via product code)
3. Snapshot & manager address setup
4. Bridge auto-deployment
5. Tool & skill installation
6. Webhook patching & profile registration
7. Full pipeline diagnostics with ping/pong test
8. Send/receive verification

### Automated integration

```bash
export AMAIL_URL=https://amail.token.tm
export AMAIL_ADMIN_KEY=your_admin_key_here
bash integrate.sh
```

## Architecture

```
                         amail-gateway
                    (external SMTP gateway)
                            │
                     ┌──────┴──────┐
                     │             │
              ┌──────┴──────┐     SMTP
              │ amail-bridge│     (outbound)
              │ (pull/push) │
              └──────┬──────┘
                     │ POST /webhooks/amail-inbound
              ┌──────┴──────┐
              │ Hermes Agent│
              │  (webhook)  │
              └──────┬──────┘
                     │ LLM + send_mail()
                     │
              ┌──────┴──────┐
              │ amail-gateway│
              │ (outbound)  │
              └─────────────┘
```

## Usage Notes

### Path convention

All runtime config lives under `~/.agentmail/{system_id}/`. The legacy
`~/.hermes/amail.json` is no longer used — do not rely on it.

### API keys belong to profiles, email addresses to personas

Each Hermes profile (e.g. `default`, `ql-biopharm`) has its own API key.
Root config `~/.agentmail/{system_id}/amail.json` holds the base profile's key.
Named profiles store keys in `profiles/{name}/amail.json`.

Email addresses can carry a **persona prefix**: `support.agent@domain` routes
to profile `agent` with persona `support`. The agent uses this to adopt the
correct identity when replying. The API key, however, is tied to the profile,
not the persona.

Activation of a named profile does NOT overwrite the root profile's key.

### No backward-compat fallback

All tools and scripts read config from `~/.agentmail/{system_id}/` paths only.
If you have older deployments with files under `~/.hermes/`, migrate them.

### Re-running integration

`integrate.sh` is idempotent — re-running detects existing config and skips
completed steps. Use `uninstall.sh` to fully clean up before a fresh start.

### Ping/pong test

```bash
python3 lib/check_status.py --ping
```

Sends a ping email through the full pipeline (SMTP → gateway → bridge → webhook)
and expects a pong response. Verifies all links without invoking the LLM.

## Project Structure

```
├── integrate.sh              # Main integration wizard (EN/ZH)
├── lib/
│   ├── helpers.sh            # UI helpers (step_*, info, ask_param)
│   ├── i18n.sh               # Bilingual strings
│   ├── check_status.py       # Pipeline diagnostics + ping/pong
│   ├── deploy_bridge.py      # Bridge download & deployment
│   ├── register_profiles.py  # Profile email registration
│   ├── send_welcome.py       # Send/receive test
│   ├── activate_system.py    # Product code activation
│   └── hermes_gateway.sh     # Multi-profile gateway management
├── tools/
│   └── amail_tools.py        # Hermes Agent runtime tools
├── patches/
│   ├── apply_webhook_patch.py
│   └── apply_profiles_patch.py
├── skill/                    # Hermes skill definitions
├── tests/                    # Integration tests
└── references/               # Design docs & architecture guides
```

## Related Projects

- [amail-gateway](https://github.com/metercai/amail-gateway) — SMTP email gateway for AI agents
- [amail-bridge](https://github.com/metercai/amail-bridge) — NAT traversal bridge for webhook delivery
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — Personal AI agent framework
