# Hermes Compatibility Record

> **Recorded:** 2026-06-11  
> **Purpose:** Audit trail of the Hermes version used to develop and validate agentmail integration patches (webhook preprocessor + profile hooks).

---

## Current Hermes Version

| Attribute | Value |
|-----------|-------|
| **HEAD Commit** | `975edd414024185809777240cd85e856573f3b6f` |
| **pyproject.toml version** | `0.16.0` |
| **git describe** | `v2026.6.5-589-g975edd414` |
| **Repo path** | `/home/ubuntu/hermes-agent` |
| **Integration patches** | `/home/ubuntu/agentmail/patches/apply_webhook_patch.py`, `apply_profiles_patch.py` |

---

## Hermes Version to Git Tag Mapping

Hermes uses date-based release tags. The pyproject.toml semver was cross-referenced with git history:

| Semver | Git Tag | Date |
|--------|---------|------|
| v0.12.0 | `v2026.4.30` | 2026-04-30 |
| v0.13.0 | `v2026.5.7` | 2026-05-07 |
| v0.14.0 | `v2026.5.16` | 2026-05-16 |
| v0.15.0 | `v2026.5.28` | 2026-05-28 |
| **v0.15.1** | **`v2026.5.29`** | **2026-05-29 (previous)** |
| v0.15.2 | `v2026.5.29.2` | 2026-05-29 |
| **v0.16.0** | **`v2026.6.5`** | **2026-06-05 (current)** |
| **HEAD** | **`975edd414`** | **post-v0.16 (589 commits)** |

---

## Target File Presence by Version

| File | v0.12 | v0.13 | v0.14 | v0.15.0 | v0.15.1 | v0.15.2 |
|------|-------|-------|-------|---------|---------|---------|
| `gateway/platforms/webhook.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hermes_cli/profiles.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cli/profiles.py` (alt path) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `toolsets.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Patch Feature Presence (native, before patching)

| Feature | v0.12 | v0.13 | v0.14 | v0.15.0 | v0.15.1 | v0.15.2 | v0.16.0 |
|---------|-------|-------|-------|---------|---------|---------|---------|
| `PREPROCESS_REGISTRY` in webhook.py | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `register_preprocessor()` function | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `preprocess` in webhook route config | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `trigger_profile_hooks()` in profiles.py | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `_HERMES_CORE_TOOLS` list in toolsets.py | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |

**Key finding:** None of the agentmail patch features exist natively in any Hermes version.
Patches always create them from scratch — they are additive, not conflict-prone.

---

## Version-to-Version Changes Relevant to Patches

| Transition | Changes | Impact on Patches |
|------------|---------|-------------------|
| **v0.12 → v0.13** | webhook: loopback detection + `INSECURE_NO_AUTH` safety rail; profiles: `--no-skills` marker | None — patch insertion points unchanged |
| **v0.13 → v0.14** | profiles: clone-all infrastructure exclusion; webhook: dynamic route security hardening, reject empty secrets | None — `# Format prompt from template` anchor still exists |
| **v0.14 → v0.15.0** | **Webhook toolset downgraded**: switched from `_HERMES_CORE_TOOLS` (24 tools) to `_HERMES_WEBHOOK_SAFE_TOOLS` (4 read-only tools); profiles: added `profile.yaml` metadata layer | **None for patches** — patches don't touch toolsets.py. Profiles patch insertion points (`logger.info("Profile ... created")`, `shutil.rmtree(profile_dir)`) unchanged. |
| v0.15.0 → v0.15.1 | Bugfix release | None |
| v0.15.1 → v0.15.2 | Bugfix release | None |
| **v0.15.2 → v0.16.0** | **webhook: disabled-route check (`enabled: false`), honcho setup hardening; profiles: Windows .bat wrapper fix, prune unused imports** | **None — patch insertion anchors unchanged** |
| **post-v0.16 HEAD** | **toolsets: added `read_terminal` to `_HERMES_CORE_TOOLS`, `\"coding\"` posture toolset; profiles: `find_alias_for_profile()`, skip 'default' in named scan** | **None — patches don't touch these** |

---

## Compatibility Matrix

| Patch | v0.12 | v0.13 | v0.14 | v0.15.0 | v0.15.1 | v0.15.2 | v0.16.0 | HEAD |
|-------|-------|-------|-------|---------|---------|---------|---------|------|
| `apply_webhook_patch.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `apply_profiles_patch.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `tools/amail_tools.py` copy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**All patches are additive-only.** They insert new functions and call sites at well-known anchor points:
- `apply_webhook_patch.py` inserts at `logger = logging.getLogger(...)` (Patch 2) and `# Format prompt from template` (Patch 3)
- `apply_profiles_patch.py` inserts at docstring `The newly created profile directory.` (Patch 1, regex match) and `shutil.rmtree(profile_dir, ...)` (Patch 2, regex match)

These insertion anchors exist unchanged across all v0.12–v0.16.0 versions and current HEAD. No patch modifies an existing function signature, removes code, or changes behavior of existing features.

---

## Patches Already Applied?

| File | Status |
|------|--------|
| `gateway/platforms/webhook.py` | **Not patched** — `PREPROCESS_REGISTRY` not found |
| `hermes_cli/profiles.py` | **Not patched** — `trigger_profile_hooks` not found |

Patches must be applied by running `integrate.sh` (steps 7 and 8) or manually.
