# AgentMail

Integration toolkit to give AI agents email capabilities via amail-gateway or agent-mail-relay.

## What it does

- Installs Hermes Agent tools for sending/receiving email
- Configures webhook routing for inbound mail
- Sets up DKIM signing and SPF verification
- Provides Python tools (`amail_tools.py`) for agent-to-mail interaction

## Quick Start

```bash
# 1. Have amail-gateway or agent-mail-relay running
# 2. Run the integration script
bash integrate.sh
```

## Structure

```
├── integrate.sh          ← Main integration script
├── amail_tools.py        ← Python tools for Hermes Agent
├── skill/                ← Hermes skill definitions
├── patches/              ← Profile/webhook patches
├── test/                 ← Integration tests
├── references/           ← Reference docs
└── docs/                 ← Integration guides (EN/ZH)
```

## Prerequisites

- amail-gateway (base edition) or agent-mail-relay (advanced edition)
- Hermes Agent
- Python 3.10+
