---
name: Python package setup in pnpm workspaces
description: Replit's Python package installation behavior in a workspace whose root is already managed by pnpm.
---

When installing Python packages in a pnpm monorepo, Replit's package manager may initialize a uv project at the workspace root and create generic Python starter files. Keep Python application dependencies and Railway deployment files in the intended Python service directory, and inspect the root diff after installation. Retain the Python runtime module configuration when the workspace needs it, but remove unrelated generated project scaffolding.

**Why:** A second package-manager project at the monorepo root can confuse project discovery and deployment buildpacks. The bot itself can still use a normal `requirements.txt` in its configured Railway root directory.

**How to apply:** After a Python package install in a pnpm workspace, inspect `git status` and review any new root-level Python files before continuing.