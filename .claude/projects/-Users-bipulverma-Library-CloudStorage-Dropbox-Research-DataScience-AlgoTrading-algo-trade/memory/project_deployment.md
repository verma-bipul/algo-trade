---
name: deployment_setup
description: Pi and Streamlit Cloud deployment details
type: project
---

**Raspberry Pi:**
- User: `aether` (NOT `pi`)
- IP: `100.105.164.8`
- Repo path: `~/algo-trade/crypto/`
- Git credentials stored (credential.helper store)
- Google credentials at `~/algo-trade/crypto/credentials.json`
- Services managed via systemd, setup.sh handles user/path substitution

**Streamlit Cloud:**
- App deployed from `verma-bipul/algo-trade`, branch `main`, file `crypto/dashboard.py`
- Secrets stored in Streamlit secrets (TOML format with [gcp_service_account] table)
- Secrets file template saved at `algo-trade/streamlit_secrets.txt` (gitignored)
- Root `requirements.txt` is for Streamlit Cloud; `crypto/requirements.txt` is for Pi

**How to apply:** When deploying changes: push to GitHub, then on Pi run `git pull && bash deploy/setup.sh`. Streamlit auto-redeploys on push.
