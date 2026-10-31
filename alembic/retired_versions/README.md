# Retired Alembic drafts

These files are preserved for audit only. Alembic does not scan this directory.

- `1a2b3c4d5e6f_admin_secondary_password.py`
- `2b3c4d5e6f7g_admin_reset_metadata.py`

They added subsets of the same `users` columns as the canonical
`8e1b2c3d4e5f_admin_secondary_reset_metadata.py`. They were never applied to
the configured development database, which is at `8e1b2c3d4e5f` and
`9cb3f04c3ba6`. Keeping them in `alembic/versions` produced three heads and
made a fresh `alembic upgrade head` fail with duplicate-column adds.

The active graph now has one head, `f0a1b2c3d4e5`, a no-op merge of
`8e1b2c3d4e5f` and `9cb3f04c3ba6`. On 24 October 2026 a throwaway PostgreSQL
database was built with `alembic upgrade head`, downgraded to
`fef3eeb03094` and upgraded to head again; all three steps succeeded and the
final revision was the merge head. The full working tree at the time of the
repair passed all 302 tests in 95.84 s with the PostgreSQL 17 client tools on
`PATH`; the migration-only commit, checked out clean, passes 300 tests. A later
migration, `c7d8e9f0a1b2`, grants `db:reset` to existing admin roles and is the
current head; the test figures above predate it. Do not move these drafts back
into `alembic/versions`
without first reconciling their column set and the `alembic_version` rows of
every database that may have applied them.
