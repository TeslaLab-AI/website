# TeslaLab AI — Engineering Instructions

## Project

TeslaLab AI is an AI-powered software maintenance platform.

The current development goal is to build the Stage 0 MVP according to the team's development requirements.

The intended product flow is:

Registration
→ Authentication
→ Dashboard
→ GitHub Connection
→ Repository Selection
→ Repository Workspace
→ Repository Scan
→ Categorized Findings
→ AI Fixing
→ Validation
→ Pull Request

---

## Technology

### Frontend
- Next.js
- TypeScript

### Backend
- Python
- FastAPI

### Database & Authentication
- Supabase
- Supabase Auth

### GitHub
- GitHub App / GitHub API

Do not introduce alternative technologies without a clear requirement or approval.

---

## Development Method

Build the system:

- Unit-by-unit
- Function-by-function
- Incrementally
- With small, reviewable changes

For every change:

1. Understand the requirement.
2. Inspect the existing code.
3. Define the smallest logical unit.
4. Implement only that unit.
5. Test it.
6. Review the Git diff.
7. Commit it.
8. Push it.
9. Move to the next unit.

Keep each push at or below 100 changed lines whenever reasonably possible, as required by the team's development workflow.

Do not combine unrelated changes into one commit.

---

## Code Changes

Before modifying code:

- Inspect the relevant existing files.
- Identify exactly what needs to change.
- Do not modify unrelated files.
- Do not rewrite working code unnecessarily.
- Do not introduce unnecessary dependencies.
- Do not redesign the architecture without approval.

Always prefer the smallest correct implementation.

---

## AI Coding Agent Rules

Before making changes:

1. Read `AGENTS.md`.
2. Read `PROJECT_CONTEXT.md` if it exists.
3. Inspect the relevant implementation.
4. Explain the intended change.
5. Make only the requested change.

The AI coding agent must:

- Never expose secrets.
- Never hardcode credentials.
- Never modify unrelated files.
- Never make large speculative changes.
- Never commit or push unless explicitly instructed.
- Report files changed.
- Report tests performed.
- Report assumptions or uncertainties.

---

## Authentication

Authentication must use Supabase Auth.

Do not store user passwords in application tables.

The dashboard must be protected from unauthenticated access.

Never expose authentication credentials or secrets in source code.

---

## Security

Never commit secrets or environment files containing secrets.

Never expose:

- API keys
- Access tokens
- Passwords
- GitHub credentials
- Supabase credentials

Use environment variables for secrets and configuration.

Do not disable security controls merely to make development easier.

---

## GitHub

GitHub access must use the authorized GitHub App/API flow.

Do not expose GitHub credentials to the frontend.

Use the minimum permissions required for each operation.

---

## AI Code Modification

AI-generated code changes must be controlled and validated.

The intended fixing flow is:

Finding
→ AI Analysis
→ Branch
→ Code Modification
→ Validation
→ Pull Request
→ Human Review

Do not directly deploy AI-generated changes to production.

---

## Deterministic Information

Use deterministic tools whenever they can establish facts.

Examples:

- Repository files
- Git diff
- Package versions
- Test results
- CI logs
- Security scan results
- Repository structure

Do not ask an LLM to guess information that can be obtained directly from the repository or a tool.

---

## Comments

Write comments when they explain non-obvious reasoning or important constraints.

Do not write comments that simply describe obvious code.

Prefer clear, readable code over excessive comments.

---

## Testing

Every logical change must be tested before committing.

Do not claim that something works without verifying it.

When a test fails:

1. Read the complete error.
2. Identify the cause.
3. Make the smallest correction.
4. Test again.
5. Review the diff.

Do not apply large automated fixes without understanding them.

---

## Git Commits

Each commit should represent one logical change.

Use clear commit messages.

Examples:

- `chore: initialize frontend`
- `feat(auth): add Supabase client`
- `feat(auth): add signup`
- `feat(auth): protect dashboard`
- `feat(github): add GitHub connection`

Avoid vague commit messages such as:

- `update`
- `changes`
- `fix`
- `final`

---

## Core Principle

Build the smallest correct thing.

Verify it.

Review the diff.

Commit it.

Push it.

Then build the next thing.