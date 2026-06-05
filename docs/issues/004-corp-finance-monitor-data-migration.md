# [Migration] Move corp-finance-monitor SQLite And File Data Into K3s Local PVC

## Summary

Cut over `corp-finance-monitor` state and file storage from the current host directory into a K3s-backed local persistent volume on `gtr`.

## Problem

The app currently stores:

- SQLite databases
- WAL/SHM files
- downloaded PDFs
- operational logs

under the host path `/srv/projects/corp-finance-monitor/data`.

That data must survive the runtime migration without corruption and with a reversible rollback path.

## Scope

- Provision a local PVC on `gtr`
- Stop legacy writers during cutover
- Checkpoint SQLite WAL files before copy
- Copy the full data tree into the new volume root
- Validate database readability and file counts
- Keep the old host data as rollback source until stability is confirmed

## Out Of Scope

- Shared distributed storage
- Multi-writer SQLite topology
- Long-term storage redesign beyond local PVC

## Acceptance Criteria

- The new backend pod can read all three SQLite databases
- File counts and total disk usage match pre-cutover baselines
- A test sync run succeeds after migration
- Rollback instructions are documented and practical

## PR Linking

- Suggested PR title: `feat: cut over corp-finance-monitor persistent data`
- GitHub issue: `#6`
- PR body should include: `Closes #6`
- Planning doc path: `docs/issues/004-corp-finance-monitor-data-migration.md`
