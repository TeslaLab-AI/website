# TeslaLab AI — Project Context

## Current Stage

Stage 0 MVP.

## Current Development Milestone

Project foundation.

## Product Flow

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

## Technology

Frontend:
- Next.js
- TypeScript

Backend:
- Python
- FastAPI

Database & Authentication:
- Supabase
- Supabase Auth

GitHub:
- GitHub App / GitHub API

## Completed

- Initialized Next.js frontend.
- Verified frontend runs locally.
- Created FastAPI backend foundation.
- Added `/health` endpoint.
- Established repository-level AI engineering instructions.
- Established root `.gitignore`.
- Removed accidentally tracked Python cache files.

## Current Repository Structure

```text
/
├── frontend/
├── backend/
├── AGENTS.md
├── CLAUDE.md
├── PROJECT_CONTEXT.md
├── README.md
└── .gitignore