# Project AGENTS.md editor

## Scope

Add one explicit editor to the local project directory browser. The editor is
available only after a configured CCM project is selected and always targets
that project's root-level `AGENTS.md`. Arbitrary paths and filenames are never
accepted by the write API.

## Data flow and safety

The frontend sends only the project id and UTF-8 content to
`GET/PUT /api/projects/{project_id}/agents-md`. The backend applies the existing
project access check, resolves the project's configured local root, and then
reads or atomically replaces only `AGENTS.md`. The repository's normal
`AGENTS.md -> CLAUDE.md` symlink is supported, while any other symlink target is
rejected. Content is limited to 1 MiB. Missing files are represented as empty
content and may be created by saving.

Worker-hosted projects are outside this first editor because the current file
browser only exposes configured local projects in its project selector.

## Interaction

Selecting a project and browsing its root enables an `Edit AGENTS.md` button.
It opens an editor in the preview pane with Save and Cancel controls. Save shows
an in-progress state, reports errors inline, refreshes the directory listing,
and keeps the saved content visible. Browsing a manual path does not enable the
project-scoped editor.

## Verification

Backend tests cover missing-file creation, existing-file updates, the canonical
`CLAUDE.md` symlink, size limits, unsafe symlinks, missing roots, and access
checks. Frontend tests cover project selection, loading the editor, saving, and
the absence of the editor for manually browsed paths.
