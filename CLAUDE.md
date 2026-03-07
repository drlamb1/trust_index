# EdgeFinder — Claude Code Instructions

## Git Workflow

**Branch protection is enabled on `main`. All changes go through PRs.**

### Parallel Sessions — Use Worktrees

Multiple Claude Code sessions run in parallel. **Each session MUST use a worktree** to avoid branch conflicts.

**At the start of every session that modifies code:**
1. Tell Claude Code: "work in a worktree" (or "start a worktree")
2. This creates an isolated checkout under `.claude/worktrees/` with its own branch
3. Work, commit, push, and PR — all isolated from other sessions
4. On session exit, you'll be prompted to keep or remove the worktree

Worktrees give each session its own working directory and branch. No session can interfere with another.

### Flow (inside a worktree)
1. You're already on an isolated branch — start coding
2. Commit freely (small, logical commits are fine)
3. Push and open a PR: `gh pr create`
4. Squash-merge the PR: `gh pr merge --squash --delete-branch`
5. Deploy: `make railway-deploy-all-3`

### Flow (single session / no worktree)
1. **Before writing any code**, check current branch: `git branch --show-current`
2. If on `main`, pull latest and create a feature branch: `git pull && git checkout -b <type>/<short-name>`
3. If already on a feature branch (not `main`), continue working there
4. Commit freely on the branch (small, logical commits are fine)
5. Push and open a PR: `gh pr create`
6. Squash-merge the PR: `gh pr merge --squash --delete-branch`
7. Deploy: `make railway-deploy-all-3`

**Critical:** Never commit to `main` directly.
If `main` has diverged, rebase: `git pull --rebase origin main`.

### Branch naming
Use `<type>/<short-description>` where type is one of:
- `fix/` — bug fixes
- `feat/` — new features
- `refactor/` — code cleanup, no behavior change
- `docs/` — documentation only
- `chore/` — deps, CI, config

Examples: `fix/pm-phantom-tools`, `feat/sse-reconnect`, `refactor/timeago-dedup`

### Commit messages
- Imperative mood, lowercase after prefix: `fix: grant PM access to 7 phantom tools`
- Keep the subject line under 72 chars
- Body is optional but encouraged for non-trivial changes

### Rules
- **First action in any task that modifies code: start a worktree (parallel) or create a feature branch (solo)**
- Never push directly to `main` — always use a PR
- Never commit to `main` — if you realize you're on `main` with uncommitted changes, stash and branch: `git stash && git checkout -b <type>/<name> && git stash pop`
- Run `make test` before opening a PR
- Deploy happens from `main` after merge, not from feature branches
- When Claude Code creates branches, it should use the naming convention above
- Subagents that modify code should use `isolation: "worktree"` to avoid touching the parent session's checkout

## Running Tests
```
make test                     # full suite, ~37s
.venv/bin/python -m pytest tests/ -q   # same thing, direct
```

## Deploying

Deploys are **automatic** on merge to `main`:
- **Backend (Railway)**: GitHub Actions deploys all 3 services sequentially + health check
- **Frontend (Vercel)**: Auto-deploys from `main` branch only (PR branches get preview URLs)

PR branches do NOT deploy to production. Vercel gives them preview URLs; Railway only deploys on main.

Manual deploy (emergency only):
```
make railway-deploy-all-3     # all 3 Railway services
```
Requires Railway CLI linked (`railway status` to verify).

## Coach (Bill Campbell Pattern)

A meta-cognitive coaching layer that sits above the work. Coaches the human AND the AI. Portable across projects.

### Commands
- `/coach` — General check-in. Reads knowledge base, scans for anti-patterns, gives honest 2-3 sentence assessment
- `/coach-review` — Before major architecture decisions. Forces simplicity/measurement/reversal-cost thinking
- `/coach-retro` — At session end or natural boundaries. What shipped, what repeated, what to change
- `/coach-experiment` — Before experiments. Requires hypothesis, metric, baseline, duration, kill condition

### When to self-invoke
The AI should apply Coach thinking (without needing the command) when it notices:
- About to create a new abstraction layer or module
- Doing something for the third time manually
- 20+ tool calls without shipping a concrete artifact
- Writing documentation for something that doesn't exist yet
- About to add a new dependency

### Files
- `.claude/commands/coach*.md` — Command definitions (portable)
- `.claude/coach/knowledge-base.md` — The Ten Practices (portable)
- `.claude/coach/anti-patterns.md` — Detected patterns (portable, grows)
- `.claude/coach/intervention-log.md` — Session history (project-specific)
- `.claude/coach/self-eval.md` — Coach accuracy tracking (portable)
- `docs/Agentic_Systems_Best_Practices_v3.md` — Full research foundation
