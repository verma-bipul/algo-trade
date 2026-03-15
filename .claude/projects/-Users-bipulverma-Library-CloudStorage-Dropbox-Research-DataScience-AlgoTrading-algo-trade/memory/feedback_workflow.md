---
name: workflow_preferences
description: User wants batched commits/pushes and to control when Pi gets updated
type: feedback
---

Don't push after every small change. Batch all changes and push once when the user says to.

**Why:** User wants to review and deploy all changes together, not piecemeal. They control when the Pi gets updated.

**How to apply:** Make all code changes locally, then wait for the user to say "push" or "update the Pi" before committing/pushing. Don't remind them to pull on the Pi after every change.
