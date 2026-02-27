---
name: git-commit-messages
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

**CRITICAL: All git commit commands MUST use the okgit wrapper:**

# Stage files first
git add <files>

# Commit with okgit wrapper (no script/TTY wrapper needed — Claude Code lacks a real TTY)
/Users/nivensie/okgit/git commit -m "<type>(<scope>): <subject>"

**NEVER use plain `git commit`.** Always use `/Users/nivensie/okgit/git commit`.

## Examples

# Single file commit
git add -A
/Users/nivensie/okgit/git commit -m "fix(kyb): correct field retrieval path"

# Multiple files commit
git add -A
/Users/nivensie/okgit/git commit -m "feat(auth): add 2FA support"

# Commit rules
- Never do a git amend. Always create a new commit.
- Always append inside the commit - 🤖 Generated with [Claude Code](https://claude.com/claude-code)
- Always add yourself as a co-author, with Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
