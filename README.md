# AgentMail

Real-time, human-like email communication for AI agents — with humans or other agents.

AgentMail wires [amail-gateway](https://github.com/metercai/amail-gateway) into
[Hermes Agent](https://github.com/nousresearch/hermes-agent), giving your AI
the ability to send and receive email through standard SMTP — no POP3/IMAP,
no polling, no mailbox configuration.

## What it does

- Installs Hermes Agent skills for sending/receiving email
- Configures webhook routing so inbound mail reaches your agent instantly
- Sets up DKIM signing and SPF verification (advanced edition)
- Provides Python tools (`amail_tools.py`) for agent-to-mail interaction

## Quick Start

```bash
# 1. Have amail-gateway running
# 2. Run the integration script
bash integrate.sh
```

## Structure

```
├── integrate.sh          # Main integration script
├── amail_tools.py        # Python tools for Hermes Agent
├── skill/                # Hermes skill definitions
├── patches/              # Profile/webhook patches
├── test/                 # Integration tests
├── references/           # Reference docs
└── docs/                 # Integration guides (EN/ZH)
```

## Prerequisites

- [amail-gateway](https://github.com/metercai/amail-gateway)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent)
- Python 3.10+
