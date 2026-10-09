---
name: git-commit
description: Generate standardized English commit messages following conventional
  commits format. Use when creating git commits or reviewing commit message quality.
---

# Git Commit Message Guidelines

Generate professional, standardized commit messages in English following
conventional commits format.

## Language Requirement

**MANDATORY: ENGLISH ONLY**
- All commit messages must be in English
- Subject, body, and footer: English only

## Format Structure

<type>(<scope>): <subject>

<body>

<footer>

## Commit Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation updates
- **style**: Code formatting (no functionality change)
- **refactor**: Code refactoring (neither feature nor bug fix)
- **test**: Test-related changes
- **chore**: Build process or auxiliary tool changes

## Subject Line

- **Format**: `<type>(<scope>): <subject>`
- **Length**: 72 characters preferred, 100 maximum
- **Subject**: Concise description in imperative mood

## Execution Command

### Stage files first. Stage the files the change touched, by name.
Run `git status --short` first, then `git add <file>...` for the files this
change is about. Use `git add -A` only when every listed change belongs to the
commit and none of them is one of the exclusions below.

Never stage:
- secrets or credentials: `.env*`, `*.pem`, `*.key`, `id_rsa*`, API-key or
  exchange-credential files;
- scratch output: probe programs, notebooks' checkpoint dirs, logs, local
  backtest artifacts the repo does not track on purpose;
- unrelated edits that happened to be in the working tree.

Name anything you left unstaged in the reply so it is not lost.

### Commit Command
If specified, use git commit title passed in the input. If not specified, make sure that the commit message follows the conventional commits format: `git commit -m "<type>(<scope>): <subject>"`

For the body, keep the summary of the commit message short, clear and as concise as possible.

## Examples

# Single file commit
git add src/kyb/fields.rs
git commit -m "fix(kyb): correct field retrieval path"

# Multiple files commit
git add src/auth/totp.rs src/auth/mod.rs tests/auth_totp.rs
git commit -m "feat(auth): add 2FA support"

# Commit rules
- Never do a git amend. Always create a new commit.
- Always append inside the commit - 🤖 Generated with [Claude Code](https://claude.com/claude-code)
