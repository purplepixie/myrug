# MyRUG: MySQL Rolling Upgrade - Quick Reference

## Installation

```bash
pip install mysql-connector-python
chmod +x myrug.py
```

## Common Commands

### Export Schema
```bash
# To file
./myrug.py export user:pass@host:3306/db -o schema.json

# To stdout
./myrug.py export user:pass@host:3306/db
```

### Generate Migration Plan
```bash
# DB to DB
./myrug.py migrate \
  user:pass@host:3306/source_db \
  user:pass@host:3306/dest_db \
  --plan -o migration.sql

# JSON to DB
./myrug.py migrate schema.json \
  user:pass@host:3306/dest_db \
  --plan
```

### Execute Migration
```bash
# Safe (with warnings check)
./myrug.py migrate schema.json \
  user:pass@host:3306/dest_db \
  --execute

# Force (ignore warnings)
./myrug.py migrate schema.json \
  user:pass@host:3306/dest_db \
  --execute --force

# Destructive (exact match)
./myrug.py migrate schema.json \
  user:pass@host:3306/dest_db \
  --execute --destructive --force
```

## Flags Quick Reference

### Export
- `-o FILE` - Output to file
- `--no-tables` - Exclude tables
- `--no-views` - Exclude views
- `--no-procedures` - Exclude procedures
- `--no-triggers` - Exclude triggers

### Migrate
- `--plan` - Generate SQL script
- `--execute` - Run migration
- `--force` - Ignore warnings
- `--destructive` - Remove extra items
- `-o FILE` - Save plan to file
- `--no-*` - Exclude specific elements

## Migration Behavior

| Flag | Behavior |
|------|----------|
| None | Add/modify only, keep extras |
| `--destructive` | Add/modify/remove for exact match |
| `--force` | Proceed despite warnings |
| `--plan` | Show SQL, don't execute |
| `--execute` | Run the migration |
| `--plan --execute` | Both show and run |

## Warning Types

- **NOT NULL without default** - Will fail on tables with data
- **Column size reduction** - May truncate data
- **Type conversion** - May lose data
- **NULL to NOT NULL** - Will fail if NULLs exist
- **Dropping items** - Will delete data

## Code Structure

### Main Components

1. **Data Models** (lines 60-250)
   - Column, Index, ForeignKey, Table
   - View, StoredProcedure, Trigger
   - Schema, Warning, MigrationStep

2. **DatabaseConnection** (lines 260-650)
   - Schema extraction from MySQL
   - Table, view, procedure, trigger extraction

3. **SchemaValidator** (lines 660-730)
   - Validation and warning generation

4. **SchemaComparator** (lines 740-1350)
   - Schema comparison logic
   - Migration plan generation
   - Intelligent operation ordering

5. **SchemaSerializer** (lines 1360-1450)
   - JSON serialization/deserialization

6. **CLI Interface** (lines 1460-end)
   - Argument parsing
   - Command execution

## Migration Stage Order

1. DROP TRIGGERS
2. DROP VIEWS
3. DROP FOREIGN_KEYS
4. DROP INDEXES
5. DROP COLUMNS
6. DROP TABLES
7. CREATE TABLES
8. ADD COLUMNS
9. MODIFY COLUMNS
10. CREATE INDEXES
11. CREATE FOREIGN_KEYS
12. CREATE VIEWS
13. CREATE PROCEDURES
14. CREATE TRIGGERS

## Best Practices

**DO:**
- Always review `--plan` output before `--execute`
- Backup databases before destructive operations
- Test on staging first
- Version control JSON schema files
- Use `--force` only after understanding warnings

**DON'T:**
- Use `--destructive` on production without backups
- Ignore warnings without understanding them
- Execute migrations without reviewing plans
- Forget to test migrations on staging

## Troubleshooting

### Connection Failed
- Check credentials
- Verify MySQL is running
- Check firewall rules
- Ensure database exists

### Permission Denied
- User needs SELECT, CREATE, ALTER, DROP
- User needs INFORMATION_SCHEMA access

### Warnings Won't Clear
- Review each warning
- Fix underlying schema issues
- Use `--force` only if intentional
