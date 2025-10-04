# MySQL Rolling Upgrade (myrug): MySQL Schema Upgrade/Migration Tool

A comprehensive Python CLI tool for managing MySQL database schema migrations. This tool can export schemas to JSON, compare schemas, and generate/execute SQL migration scripts with intelligent ordering and safety checks.

Licenced under the GNU General Public Licence (GPL) v3 (or later).

Aspects of this work may have been created/augmented/assisted by AI tools.

## Features

- **Export schemas** to JSON format for version control and backup
- **Compare schemas** between databases or JSON files
- **Generate SQL migration scripts** with proper ordering of operations
- **Execute migrations** directly to databases
- **Comprehensive warnings** for potentially dangerous operations
- **Support for all MySQL schema elements**:
  - Tables (columns, data types, constraints)
  - Primary keys
  - Indexes (including unique indexes)
  - Foreign keys with cascading rules
  - Views
  - Stored procedures and functions
  - Triggers
- **Intelligent operation ordering** (e.g., drops FKs before dropping tables)
- **Data loss detection** (warns about lossy type changes)
- **Flexible options** to include/exclude specific schema elements

## Installation

### Prerequisites

- Python 3.8 or higher
- MySQL database access

### Install Dependencies

```bash
pip install mysql-connector-python
```

Or use the requirements file:

```bash
pip install -r requirements.txt
```

### Make the Script Executable

```bash
chmod +x myrug.py
```

## Usage

### Connection String Format

The tool uses connection strings in the format:
```
user:password@host:port/database
```

Examples:
- `root:mypassword@localhost:3306/mydb`
- `admin:secret@192.168.1.100:3306/production`

### Export Command

Export a database schema to JSON format:

```bash
# Export to stdout
./myrug.py export root:pass@localhost:3306/mydb

# Export to file
./myrug.py export root:pass@localhost:3306/mydb -o schema.json

# Export only tables (exclude views, procedures, triggers)
./myrug.py export root:pass@localhost:3306/mydb \
  --no-views --no-procedures --no-triggers -o tables_only.json
```

### Migrate Command

Generate and/or execute schema migrations:

```bash
# Generate migration plan from one database to another (display on stdout)
./myrug.py migrate \
  root:pass@localhost:3306/source_db \
  root:pass@localhost:3306/dest_db \
  --plan

# Save migration plan to file
./myrug.py migrate \
  root:pass@localhost:3306/source_db \
  root:pass@localhost:3306/dest_db \
  --plan -o migration.sql

# Migrate from JSON file to database
./myrug.py migrate \
  schema.json \
  root:pass@localhost:3306/dest_db \
  --plan

# Execute migration (with warnings check)
./myrug.py migrate \
  schema.json \
  root:pass@localhost:3306/dest_db \
  --execute

# Execute migration ignoring warnings
./myrug.py migrate \
  schema.json \
  root:pass@localhost:3306/dest_db \
  --execute --force

# Destructive migration (removes extra tables/columns/etc. from destination)
./myrug.py migrate \
  schema.json \
  root:pass@localhost:3306/dest_db \
  --execute --destructive --force

# Generate and execute in one command
./myrug.py migrate \
  schema.json \
  root:pass@localhost:3306/dest_db \
  --plan --execute -o migration.sql
```

## Command-Line Options

### Global Options

None currently (all options are command-specific)

### Export Command Options

- `source` (required): Database connection string
- `-o, --output`: Output JSON file path (default: stdout)
- `--no-tables`: Exclude tables from export
- `--no-views`: Exclude views from export
- `--no-procedures`: Exclude stored procedures from export
- `--no-triggers`: Exclude triggers from export

### Migrate Command Options

- `source` (required): Source database connection string or JSON file path
- `destination` (required): Destination database connection string
- `--plan`: Generate SQL migration script
- `--execute`: Execute the migration on the destination database
- `--force`: Proceed even if warnings are generated
- `--destructive`: Remove items from destination that don't exist in source
- `-o, --output`: Output file for migration plan (default: stdout)
- `--no-tables`: Exclude tables from migration
- `--no-views`: Exclude views from migration
- `--no-procedures`: Exclude stored procedures from migration
- `--no-triggers`: Exclude triggers from migration

## Migration Behavior

### Non-Destructive Mode (Default)

By default, migrations are **non-destructive**:
- New tables, columns, indexes, etc. are **added**
- Existing items are **modified** if they differ
- Items in the destination that don't exist in the source are **preserved**

This is safe for most scenarios where you want to update a schema without losing anything.

### Destructive Mode (`--destructive`)

With the `--destructive` flag, the destination schema will be made to **exactly match** the source:
- New items are **added**
- Changed items are **modified**
- Extra items are **removed** (tables, columns, indexes, foreign keys, views, procedures, triggers)

**Warning**: This will delete data if tables or columns are dropped!

### Force Mode (`--force`)

By default, if the tool detects warnings (e.g., adding a NOT NULL column without a default), it will stop and display the warnings. Use `--force` to proceed anyway.

## Warning System

The tool generates warnings for potentially problematic operations:

- **Adding NOT NULL columns** without defaults to tables with data
- **Reducing column sizes** (e.g., VARCHAR(100) → VARCHAR(50))
- **Changing column types** that might lose data
- **Changing NULL to NOT NULL** on columns that might contain NULL values
- **Dropping tables/columns** (with `--destructive`)
- **Missing primary keys** (informational)

## Migration Stages

The tool orders operations intelligently to avoid dependency issues:

1. **Drop Triggers** - First, as they depend on tables
2. **Drop Views** - Second, as they depend on tables
3. **Drop Foreign Keys** - Before dropping or modifying tables
4. **Drop Indexes** - Before table modifications
5. **Drop Columns** - Before table drops
6. **Drop Tables** - After removing dependencies
7. **Create Tables** - New tables
8. **Add Columns** - New columns to existing tables
9. **Modify Columns** - Change column definitions
10. **Create Indexes** - After tables and columns exist
11. **Create Foreign Keys** - After referenced tables exist
12. **Create Views** - After tables exist
13. **Create Procedures** - After tables exist
14. **Create Triggers** - Last, as they depend on tables

## JSON Schema Format

The exported JSON includes complete schema information:

```json
{
  "database_name": "mydb",
  "tables": {
    "users": {
      "name": "users",
      "columns": [
        {
          "name": "id",
          "data_type": "INT",
          "is_nullable": false,
          "default": null,
          "extra": "auto_increment",
          "character_set": null,
          "collation": null,
          "comment": ""
        }
      ],
      "primary_key": ["id"],
      "indexes": [],
      "foreign_keys": [],
      "engine": "InnoDB",
      "charset": "utf8mb4",
      "collation": "utf8mb4_unicode_ci",
      "comment": ""
    }
  },
  "views": {},
  "procedures": {},
  "triggers": {}
}
```

## Examples

### Example 1: Version Control Your Schema

```bash
# Export production schema
./myrug.py export \
  prod_user:pass@prod-server:3306/mydb \
  -o schemas/production_v1.0.json

# Commit to git
git add schemas/production_v1.0.json
git commit -m "Schema snapshot v1.0"
```

### Example 2: Sync Dev to Production

```bash
# Export development schema
./myrug.py export \
  dev:pass@localhost:3306/dev_db \
  -o dev_schema.json

# Review migration plan
./myrug.py migrate \
  dev_schema.json \
  prod:pass@prod-server:3306/prod_db \
  --plan -o migration_plan.sql

# Review migration_plan.sql manually
# If satisfied, execute
./myrug.py migrate \
  dev_schema.json \
  prod:pass@prod-server:3306/prod_db \
  --execute --force
```

### Example 3: Database Refactoring

```bash
# You have an old database and want to restructure it
# Export current state
./myrug.py export \
  root:pass@localhost:3306/old_db \
  -o old_schema.json

# Create new database with desired structure manually
# Then generate migration to convert old_db to new structure
./myrug.py migrate \
  root:pass@localhost:3306/new_db \
  root:pass@localhost:3306/old_db \
  --plan --destructive -o refactor.sql

# Review and execute
./myrug.py migrate \
  root:pass@localhost:3306/new_db \
  root:pass@localhost:3306/old_db \
  --execute --destructive --force
```

### Example 4: Tables Only Migration

```bash
# Only migrate table structures (skip views, procedures, triggers)
./myrug.py migrate \
  source.json \
  root:pass@localhost:3306/dest_db \
  --no-views --no-procedures --no-triggers \
  --plan --execute
```

## Best Practices

1. **Always review migration plans** before executing
2. **Backup your database** before running destructive migrations
3. **Test migrations** on a staging database first
4. **Use version control** for schema JSON files
5. **Document changes** in commit messages when updating schema files
6. **Use --force carefully** - understand the warnings before proceeding
7. **Avoid --destructive** unless you're certain you want exact schema matching

## Error Handling

The tool provides detailed error messages:
- Connection failures show connection details
- SQL errors during execution are caught and rolled back
- Invalid connection strings are detected and reported
- Missing JSON files are reported clearly

## Troubleshooting

### Connection Issues

If you get connection errors:
1. Verify the connection string format
2. Check that MySQL server is running
3. Verify credentials are correct
4. Ensure the database exists
5. Check firewall rules for remote connections

### Permission Issues

The MySQL user needs appropriate permissions:
- `SELECT` - To read schema information
- `CREATE, ALTER, DROP` - To execute migrations
- Access to `INFORMATION_SCHEMA` - To extract metadata

### Warnings Won't Clear

If you get persistent warnings:
1. Review each warning carefully
2. Fix the underlying issues in your schema if possible
3. Use `--force` only if you understand the implications

## Contributing

This tool is designed to be extensible. Key areas for enhancement:
- Support for more MySQL features (partitions, etc.)
- Better diff visualization
- Interactive mode for reviewing changes
- Rollback generation
- Support for other databases (PostgreSQL, etc.)

## License

GNU GPL (General Purpose Licence) version 3 (or later).

## Author

David Cutting - https://davecutting.uk/
