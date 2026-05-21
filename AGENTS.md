# Project Agent Instructions

## Project context

This is the `auto_he_llegado` desktop automation app.

The project includes:
- automation flows for Paripe, Compinche, and Ready4Drive
- Playwright browser automation
- photo pool/uploader logic
- Supabase storage/database integration
- admin/debug/export tools
- UI panels for process status, uploader, cleanup, and diagnostics

## Use installed Codex tools

Codex has access to these installed capabilities:

- plugin: `superpowers`
- skill: `ui-ux-pro-max`

Use them when relevant.

## Superpowers usage

Use `superpowers` for:
- systematic debugging
- writing implementation plans
- verification before completion
- test-driven changes
- code review style reasoning
- finishing development branches
- breaking complex changes into safe steps

Before making risky changes, prefer a short plan:
1. identify current behavior
2. identify desired behavior
3. isolate the smallest safe change
4. add or update tests
5. run validation

Do not use superpowers as an excuse to broaden scope.

## ui-ux-pro-max usage

Use `ui-ux-pro-max` when modifying or reviewing UI/UX, especially:
- `ui/`
- admin panel
- uploader panel
- cleanup photos panel
- diagnostics/export screens
- process status cards
- error/status messages
- progress bars
- layout, spacing, readability, color, and interaction states

When working on UI:
- preserve the current dark visual style unless explicitly asked otherwise
- keep the app practical and compact
- avoid unnecessary animations
- prioritize clarity, readable status, and visible progress
- make errors actionable
- do not mix UI refactors with automation-flow logic changes unless requested

## Critical automation rules

Do not casually change:
- login behavior
- selfie/photo upload flow
- final click logic
- Flow State Detector rules
- BrowserManager behavior
- Supabase schema
- uploader bulk logic
- photo cleanup logic
- multiprocessing isolation

For automation changes:
- keep changes site-scoped when requested
- preserve fallbacks
- add tests for regressions
- run targeted tests and full tests when possible

## Paripe current optimization rules

Paripe has a fast final-click path using Flow State Detector.

Expected behavior:
- after `final_click_done`, do not run old block-reading routes
- no `block_read_ready` after final click
- no `block_details_read` after final click
- no double final click
- `final_result_started` should happen immediately after `final_click_done`
- `final_result_done` and `process_finished` should be close together
- fallback traditional route must remain available before final click

## Validation

For automation changes, run relevant checks such as:

```powershell
python -m py_compile automation\paripe_site.py
python -m py_compile automation\compinche_site.py
python -m py_compile automation\ready4drive_site.py
python -m py_compile services\process_service.py
python -m pytest tests\test_paripe_site.py
python -m pytest tests\test_process_service.py
python -m pytest tests -q