---
name: commit
description: Stage and commit the current working-tree changes with a clear, conventional message — reviews the diffs, writes the message, commits, and verifies.
---

# commit

Create a git commit for the current working-tree changes — reviews what changed,
writes a clear conventional message, stages the files, and commits.

## Usage

```
/commit
```

## What it does

1. **Review** — run `git status --short` and `git diff --stat`; read the actual
   diffs (`git diff`, plus `git diff --cached` if anything is already staged).
2. **Style** — check `git log --oneline -5` to match the repo's commit style.
3. **Message** — write an imperative subject (≤ ~72 chars, e.g. "Fix…", "Add…",
   "Update…") with a body of bullets describing what and why, one per logical
   change. End the message with:
   `Co-Authored-By: Claude <noreply@anthropic.com>`
4. **Stage** — `git add -A` by default. If the working tree contains unrelated
   changes, ask the user which files to include rather than committing everything.
5. **Commit** — `git commit -F - <<'MSG' … MSG` (heredoc) or multiple `-m` flags:
   `git commit -m "subject" -m "body line"` (avoid a single multiline `-m "…"`).
6. **Verify** — `git status` shows a clean tree and `git log -1 --oneline` shows
   the new commit.

## Safety rules

- Never `git push --force`, never amend without asking, never bypass hooks
  (`--no-verify`), never sign with `-S` unless requested.
- **Secrets** — scan the diff for `.env`, API keys, tokens, or credentials before
  staging; do NOT commit them. Point the user to `.env`/`.env.example` instead.
- Don't commit generated or ignored artifacts; confirm against `git status` first.
- If a pre-commit hook fails, investigate and fix the underlying issue — don't
  skip the hook.

## Example

```
/commit
# → reviews diffs, stages everything, commits:
# Fix AI food-modifier questions for spice, protein, and paid choices
```

## Related

- [CLAUDE.md](/CLAUDE.md) — project commands and conventions
