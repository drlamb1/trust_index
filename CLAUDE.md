# EdgeFinder — Claude Code Instructions

## Git Workflow

**Branch protection is enabled on `main`. All changes go through PRs.**

### Flow
1. Create a feature branch off `main`: `git checkout -b <type>/<short-name>`
2. Commit freely on the branch (small, logical commits are fine)
3. Push and open a PR: `gh pr create`
4. Squash-merge the PR: `gh pr merge --squash --delete-branch`
5. Deploy: `make railway-deploy-all-3`

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
- Never push directly to `main` — always use a PR
- Run `make test` before opening a PR
- Deploy happens from `main` after merge, not from feature branches
- When Claude Code creates branches, it should use the naming convention above

## Running Tests
```
make test                     # full suite, ~37s
.venv/bin/python -m pytest tests/ -q   # same thing, direct
```

## Deploying
```
make railway-deploy-all-3     # all 3 Railway services
```
Requires Railway CLI linked (`railway status` to verify).
