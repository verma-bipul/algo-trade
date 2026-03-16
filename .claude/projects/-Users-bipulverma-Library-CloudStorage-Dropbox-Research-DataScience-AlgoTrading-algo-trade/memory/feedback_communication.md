---
name: communication_style
description: User wants concise output, no verbose data dumps, explain infrastructure concepts clearly
type: feedback
---

Don't dump large outputs (like full JSON credentials or entire file contents) into the conversation. Keep things concise.

**Why:** User got frustrated when full credentials.json was printed and when dashboard showed too much trade data. They want brief, actionable output.

**How to apply:** Summarize data instead of showing it raw. For secrets/credentials, write to a file and tell user to open it. For dashboard displays, keep compact. When explaining infrastructure (systemd, TOML, service accounts), explain simply — user is not a DevOps expert.
