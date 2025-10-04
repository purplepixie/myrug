#!/usr/bin/env python3
"""
MyRUG - MySQL Rolling Upgrade, a MySQL Schema Migration Tool

A CLI tool for MySQL database schema management that can:
- Export database schemas to JSON
- Compare schemas between databases or JSON files
- Generate SQL migration scripts
- Execute migrations with safety checks
- Handle tables, indexes, foreign keys, views, procedures, and triggers

Please note this is the updated Python implementation of the old
"MySQL Rough Upgrader" PHP scripts.

MyRUG is (C) Copyright 2025 David Cutting, https://davecutting.uk

MyRUG is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

MyRUG is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with MyRUG.  If not, see www.gnu.org/licenses

For more information see www.purplepixie.org/myrug
"""

import argparse
import json
import sys
import re
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    print("Error: mysql-connector-python is not installed.", file=sys.stderr)
    print("Install it with: pip install mysql-connector-python", file=sys.stderr)
    sys.exit(1)


# ============================================================================
# CONSTANTS AND ENUMS
# ============================================================================

class WarningLevel(Enum):
    """Enum for categorizing warning severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class MigrationStage(Enum):
    """Enum for different stages of migration to ensure proper ordering."""
    DROP_TRIGGERS = 1
    DROP_VIEWS = 2
    DROP_FOREIGN_KEYS = 3
    DROP_INDEXES = 4
    DROP_COLUMNS = 5
    DROP_TABLES = 6
    CREATE_TABLES = 7
    ADD_COLUMNS = 8
    MODIFY_COLUMNS = 9
    CREATE_INDEXES = 10
    CREATE_FOREIGN_KEYS = 11
    CREATE_VIEWS = 12
    CREATE_PROCEDURES = 13
    CREATE_TRIGGERS = 14


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class Column:
    """
    Represents a table column with all its properties.
    
    Attributes:
        name: Column name
        data_type: MySQL data type (e.g., 'VARCHAR(255)', 'INT')
        is_nullable: Whether NULL values are allowed
        default: Default value (None if no default)
        extra: Extra attributes (e.g., 'auto_increment')
        character_set: Character set for string columns
        collation: Collation for string columns
        comment: Column comment
    """
    name: str
    data_type: str
    is_nullable: bool
    default: Optional[str] = None
    extra: str = ""
    character_set: Optional[str] = None
    collation: Optional[str] = None
    comment: str = ""

    def __eq__(self, other):
        """Compare columns for equality (used in schema comparison)."""
        if not isinstance(other, Column):
            return False
        return (
            self.name == other.name and
            self.data_type.upper() == other.data_type.upper() and
            self.is_nullable == other.is_nullable and
            self.default == other.default and
            self.extra == other.extra and
            self.character_set == other.character_set and
            self.collation == other.collation
        )


@dataclass
class Index:
    """
    Represents a table index.
    
    Attributes:
        name: Index name
        columns: List of column names in the index
        is_unique: Whether this is a unique index
        index_type: Type of index (BTREE, HASH, etc.)
    """
    name: str
    columns: List[str]
    is_unique: bool
    index_type: str = "BTREE"

    def __eq__(self, other):
        """Compare indexes for equality."""
        if not isinstance(other, Index):
            return False
        return (
            self.name == other.name and
            self.columns == other.columns and
            self.is_unique == other.is_unique and
            self.index_type == other.index_type
        )


@dataclass
class ForeignKey:
    """
    Represents a foreign key constraint.
    
    Attributes:
        name: Foreign key constraint name
        columns: List of columns in this table
        referenced_table: Name of the referenced table
        referenced_columns: List of columns in the referenced table
        on_delete: Action on delete (CASCADE, SET NULL, etc.)
        on_update: Action on update
    """
    name: str
    columns: List[str]
    referenced_table: str
    referenced_columns: List[str]
    on_delete: str = "RESTRICT"
    on_update: str = "RESTRICT"

    def __eq__(self, other):
        """Compare foreign keys for equality."""
        if not isinstance(other, ForeignKey):
            return False
        return (
            self.columns == other.columns and
            self.referenced_table == other.referenced_table and
            self.referenced_columns == other.referenced_columns and
            self.on_delete == other.on_delete and
            self.on_update == other.on_update
        )


@dataclass
class Table:
    """
    Represents a database table with all its components.
    
    Attributes:
        name: Table name
        columns: List of Column objects
        primary_key: List of column names in the primary key
        indexes: List of Index objects
        foreign_keys: List of ForeignKey objects
        engine: Storage engine (InnoDB, MyISAM, etc.)
        charset: Default character set
        collation: Default collation
        comment: Table comment
    """
    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    engine: str = "InnoDB"
    charset: Optional[str] = None
    collation: Optional[str] = None
    comment: str = ""


@dataclass
class View:
    """
    Represents a database view.
    
    Attributes:
        name: View name
        definition: SQL definition of the view
        check_option: Check option (CASCADED, LOCAL, NONE)
        security_type: Security type (DEFINER, INVOKER)
    """
    name: str
    definition: str
    check_option: str = "NONE"
    security_type: str = "DEFINER"


@dataclass
class StoredProcedure:
    """
    Represents a stored procedure or function.
    
    Attributes:
        name: Procedure/function name
        type: 'PROCEDURE' or 'FUNCTION'
        definition: SQL definition
        parameters: Parameter definitions
        returns: Return type (for functions)
    """
    name: str
    type: str  # PROCEDURE or FUNCTION
    definition: str
    parameters: str = ""
    returns: Optional[str] = None


@dataclass
class Trigger:
    """
    Represents a database trigger.
    
    Attributes:
        name: Trigger name
        table: Table the trigger is attached to
        timing: BEFORE or AFTER
        event: INSERT, UPDATE, or DELETE
        definition: SQL definition
    """
    name: str
    table: str
    timing: str
    event: str
    definition: str


@dataclass
class Schema:
    """
    Complete database schema representation.
    
    Attributes:
        tables: Dictionary of table_name -> Table
        views: Dictionary of view_name -> View
        procedures: Dictionary of procedure_name -> StoredProcedure
        triggers: Dictionary of trigger_name -> Trigger
        database_name: Name of the database
    """
    tables: Dict[str, Table] = field(default_factory=dict)
    views: Dict[str, View] = field(default_factory=dict)
    procedures: Dict[str, StoredProcedure] = field(default_factory=dict)
    triggers: Dict[str, Trigger] = field(default_factory=dict)
    database_name: str = ""


@dataclass
class Warning:
    """
    Represents a warning or error found during validation.
    
    Attributes:
        level: Severity level
        message: Description of the warning
        context: Additional context (table name, column name, etc.)
    """
    level: WarningLevel
    message: str
    context: str = ""


@dataclass
class MigrationStep:
    """
    Represents a single migration step.
    
    Attributes:
        stage: Migration stage for ordering
        sql: SQL command to execute
        description: Human-readable description
        warnings: List of warnings associated with this step
    """
    stage: MigrationStage
    sql: str
    description: str
    warnings: List[Warning] = field(default_factory=list)


# ============================================================================
# DATABASE CONNECTION AND SCHEMA EXTRACTION
# ============================================================================

class DatabaseConnection:
    """
    Manages MySQL database connections and provides schema extraction methods.
    """

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        """
        Initialize database connection parameters.
        
        Args:
            host: Database host
            port: Database port
            user: Database user
            password: Database password
            database: Database name
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.connection = None

    def __enter__(self):
        """Context manager entry - establish connection."""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database
            )
            return self
        except MySQLError as e:
            print(f"Error connecting to database: {e}", file=sys.stderr)
            sys.exit(1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()

    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[tuple]:
        """
        Execute a query and return results.
        
        Args:
            query: SQL query to execute
            params: Optional query parameters
            
        Returns:
            List of result tuples
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(query, params or ())
            return cursor.fetchall()
        finally:
            cursor.close()

    def extract_tables(self) -> Dict[str, Table]:
        """
        Extract all tables from the database.
        
        Returns:
            Dictionary mapping table names to Table objects
        """
        tables = {}
        
        # Get list of all tables
        table_names = self.execute_query("SHOW TABLES")
        
        for (table_name,) in table_names:
            table = Table(name=table_name)
            
            # Extract table metadata
            table_status = self.execute_query(f"SHOW TABLE STATUS LIKE '{table_name}'")
            if table_status:
                status = table_status[0]
                table.engine = status[1] or "InnoDB"
                table.charset = status[14]
                table.collation = status[14]  # Collation is typically at index 14
                table.comment = status[17] or ""
            
            # Extract columns
            table.columns = self._extract_columns(table_name)
            
            # Extract primary key
            table.primary_key = self._extract_primary_key(table_name)
            
            # Extract indexes
            table.indexes = self._extract_indexes(table_name, table.primary_key)
            
            # Extract foreign keys
            table.foreign_keys = self._extract_foreign_keys(table_name)
            
            tables[table_name] = table
        
        return tables

    def _extract_columns(self, table_name: str) -> List[Column]:
        """
        Extract columns for a specific table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of Column objects
        """
        columns = []
        
        # Use SHOW FULL COLUMNS to get complete column information
        query = f"SHOW FULL COLUMNS FROM `{table_name}`"
        rows = self.execute_query(query)
        
        for row in rows:
            # Parse the column information
            # Format: Field, Type, Collation, Null, Key, Default, Extra, Privileges, Comment
            column = Column(
                name=row[0],
                data_type=row[1],
                is_nullable=(row[3] == 'YES'),
                default=row[5],
                extra=row[6] or "",
                collation=row[2],
                comment=row[8] or ""
            )
            
            # Extract character set from collation if present
            if column.collation:
                column.character_set = column.collation.split('_')[0]
            
            columns.append(column)
        
        return columns

    def _extract_primary_key(self, table_name: str) -> List[str]:
        """
        Extract primary key columns for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of column names in the primary key
        """
        query = """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY ORDINAL_POSITION
        """
        rows = self.execute_query(query, (self.database, table_name))
        return [row[0] for row in rows]

    def _extract_indexes(self, table_name: str, primary_key: List[str]) -> List[Index]:
        """
        Extract indexes for a table (excluding primary key).
        
        Args:
            table_name: Name of the table
            primary_key: List of primary key columns (to exclude)
            
        Returns:
            List of Index objects
        """
        indexes = {}
        
        # Get index information
        query = f"SHOW INDEX FROM `{table_name}`"
        rows = self.execute_query(query)
        
        for row in rows:
            index_name = row[2]
            
            # Skip primary key as it's handled separately
            if index_name == 'PRIMARY':
                continue
            
            # Initialize index if not seen before
            if index_name not in indexes:
                indexes[index_name] = {
                    'columns': [],
                    'is_unique': not bool(row[1]),  # Non_unique column
                    'index_type': row[10]  # Index_type column
                }
            
            # Add column to index (maintaining order)
            indexes[index_name]['columns'].append(row[4])  # Column_name
        
        # Convert to Index objects
        return [
            Index(
                name=name,
                columns=data['columns'],
                is_unique=data['is_unique'],
                index_type=data['index_type']
            )
            for name, data in indexes.items()
        ]

    def _extract_foreign_keys(self, table_name: str) -> List[ForeignKey]:
        """
        Extract foreign keys for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of ForeignKey objects
        """
        foreign_keys = {}
        
        query = """
            SELECT
                kcu.CONSTRAINT_NAME,
                kcu.COLUMN_NAME,
                kcu.REFERENCED_TABLE_NAME,
                kcu.REFERENCED_COLUMN_NAME,
                rc.UPDATE_RULE,
                rc.DELETE_RULE
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
            JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
                AND kcu.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA
            WHERE kcu.TABLE_SCHEMA = %s
              AND kcu.TABLE_NAME = %s
              AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
        """
        rows = self.execute_query(query, (self.database, table_name))
        
        for row in rows:
            constraint_name = row[0]
            
            # Initialize foreign key if not seen before
            if constraint_name not in foreign_keys:
                foreign_keys[constraint_name] = {
                    'columns': [],
                    'referenced_table': row[2],
                    'referenced_columns': [],
                    'on_update': row[4],
                    'on_delete': row[5]
                }
            
            # Add column information
            foreign_keys[constraint_name]['columns'].append(row[1])
            foreign_keys[constraint_name]['referenced_columns'].append(row[3])
        
        # Convert to ForeignKey objects
        return [
            ForeignKey(
                name=name,
                columns=data['columns'],
                referenced_table=data['referenced_table'],
                referenced_columns=data['referenced_columns'],
                on_update=data['on_update'],
                on_delete=data['on_delete']
            )
            for name, data in foreign_keys.items()
        ]

    def extract_views(self) -> Dict[str, View]:
        """
        Extract all views from the database.
        
        Returns:
            Dictionary mapping view names to View objects
        """
        views = {}
        
        query = """
            SELECT
                TABLE_NAME,
                VIEW_DEFINITION,
                CHECK_OPTION,
                SECURITY_TYPE
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s
        """
        rows = self.execute_query(query, (self.database,))
        
        for row in rows:
            views[row[0]] = View(
                name=row[0],
                definition=row[1],
                check_option=row[2] or "NONE",
                security_type=row[3]
            )
        
        return views

    def extract_procedures(self) -> Dict[str, StoredProcedure]:
        """
        Extract all stored procedures and functions from the database.
        
        Returns:
            Dictionary mapping procedure names to StoredProcedure objects
        """
        procedures = {}
        
        # Get procedures and functions
        query = """
            SELECT
                ROUTINE_NAME,
                ROUTINE_TYPE,
                DTD_IDENTIFIER
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_SCHEMA = %s
        """
        rows = self.execute_query(query, (self.database,))
        
        for row in rows:
            routine_name = row[0]
            routine_type = row[1]  # PROCEDURE or FUNCTION
            returns = row[2] if routine_type == 'FUNCTION' else None
            
            # Get the full definition
            show_query = f"SHOW CREATE {routine_type} `{routine_name}`"
            try:
                result = self.execute_query(show_query)
                if result:
                    definition = result[0][2]  # CREATE statement
                    
                    procedures[routine_name] = StoredProcedure(
                        name=routine_name,
                        type=routine_type,
                        definition=definition,
                        returns=returns
                    )
            except MySQLError:
                # Skip if we can't access the procedure definition
                pass
        
        return procedures

    def extract_triggers(self) -> Dict[str, Trigger]:
        """
        Extract all triggers from the database.
        
        Returns:
            Dictionary mapping trigger names to Trigger objects
        """
        triggers = {}
        
        query = """
            SELECT
                TRIGGER_NAME,
                EVENT_OBJECT_TABLE,
                ACTION_TIMING,
                EVENT_MANIPULATION,
                ACTION_STATEMENT
            FROM INFORMATION_SCHEMA.TRIGGERS
            WHERE TRIGGER_SCHEMA = %s
        """
        rows = self.execute_query(query, (self.database,))
        
        for row in rows:
            triggers[row[0]] = Trigger(
                name=row[0],
                table=row[1],
                timing=row[2],  # BEFORE or AFTER
                event=row[3],   # INSERT, UPDATE, or DELETE
                definition=row[4]
            )
        
        return triggers

    def extract_schema(self, include_tables: bool = True, include_views: bool = True,
                      include_procedures: bool = True, include_triggers: bool = True) -> Schema:
        """
        Extract the complete database schema.
        
        Args:
            include_tables: Whether to include tables
            include_views: Whether to include views
            include_procedures: Whether to include stored procedures
            include_triggers: Whether to include triggers
            
        Returns:
            Complete Schema object
        """
        schema = Schema(database_name=self.database)
        
        if include_tables:
            schema.tables = self.extract_tables()
        
        if include_views:
            schema.views = self.extract_views()
        
        if include_procedures:
            schema.procedures = self.extract_procedures()
        
        if include_triggers:
            schema.triggers = self.extract_triggers()
        
        return schema


# ============================================================================
# SCHEMA VALIDATION AND WARNING GENERATION
# ============================================================================

class SchemaValidator:
    """
    Validates schemas and generates warnings for potential issues.
    """

    @staticmethod
    def validate_schema(schema: Schema) -> List[Warning]:
        """
        Validate a schema and return any warnings found.
        
        Args:
            schema: Schema to validate
            
        Returns:
            List of Warning objects
        """
        warnings = []
        
        for table_name, table in schema.tables.items():
            warnings.extend(SchemaValidator._validate_table(table))
        
        return warnings

    @staticmethod
    def _validate_table(table: Table) -> List[Warning]:
        """
        Validate a single table.
        
        Args:
            table: Table to validate
            
        Returns:
            List of warnings for this table
        """
        warnings = []
        
        # Check for columns that cannot be null without a default
        for column in table.columns:
            if not column.is_nullable and column.default is None and 'auto_increment' not in column.extra.lower():
                warnings.append(Warning(
                    level=WarningLevel.WARNING,
                    message=f"Column '{column.name}' cannot be NULL and has no default value. "
                           f"Adding this column to a table with existing data will fail.",
                    context=f"Table: {table.name}"
                ))
        
        # Check for missing primary key
        if not table.primary_key:
            warnings.append(Warning(
                level=WarningLevel.INFO,
                message="Table has no primary key defined.",
                context=f"Table: {table.name}"
            ))
        
        # Check for foreign keys referencing non-existent columns
        for fk in table.foreign_keys:
            if len(fk.columns) != len(fk.referenced_columns):
                warnings.append(Warning(
                    level=WarningLevel.ERROR,
                    message=f"Foreign key '{fk.name}' has mismatched column counts.",
                    context=f"Table: {table.name}"
                ))
        
        return warnings


# ============================================================================
# SCHEMA COMPARISON AND MIGRATION PLAN GENERATION
# ============================================================================

class SchemaComparator:
    """
    Compares two schemas and generates migration steps.
    """

    def __init__(self, source: Schema, destination: Schema, destructive: bool = False):
        """
        Initialize the schema comparator.
        
        Args:
            source: Source schema (target state)
            destination: Destination schema (current state)
            destructive: Whether to generate destructive operations
        """
        self.source = source
        self.destination = destination
        self.destructive = destructive
        self.migration_steps: List[MigrationStep] = []
        self.warnings: List[Warning] = []

    def generate_migration_plan(self, include_tables: bool = True, include_views: bool = True,
                                include_procedures: bool = True, include_triggers: bool = True) -> List[MigrationStep]:
        """
        Generate a complete migration plan.
        
        Args:
            include_tables: Whether to include table migrations
            include_views: Whether to include view migrations
            include_procedures: Whether to include procedure migrations
            include_triggers: Whether to include trigger migrations
            
        Returns:
            List of MigrationStep objects in execution order
        """
        self.migration_steps = []
        self.warnings = []
        
        if include_triggers:
            self._compare_triggers()
        
        if include_views:
            self._compare_views()
        
        if include_tables:
            self._compare_tables()
        
        if include_procedures:
            self._compare_procedures()
        
        # Sort steps by stage to ensure proper execution order
        self.migration_steps.sort(key=lambda step: step.stage.value)
        
        return self.migration_steps

    def _compare_tables(self):
        """Compare tables between source and destination schemas."""
        source_tables = set(self.source.tables.keys())
        dest_tables = set(self.destination.tables.keys())
        
        # Tables to drop (exist in destination but not in source)
        if self.destructive:
            for table_name in dest_tables - source_tables:
                self._generate_drop_table(table_name)
        
        # Tables to create (exist in source but not in destination)
        for table_name in source_tables - dest_tables:
            self._generate_create_table(self.source.tables[table_name])
        
        # Tables to modify (exist in both)
        for table_name in source_tables & dest_tables:
            self._compare_table_structure(
                self.source.tables[table_name],
                self.destination.tables[table_name]
            )

    def _generate_drop_table(self, table_name: str):
        """Generate step to drop a table."""
        step = MigrationStep(
            stage=MigrationStage.DROP_TABLES,
            sql=f"DROP TABLE IF EXISTS `{table_name}`;",
            description=f"Drop table '{table_name}'"
        )
        step.warnings.append(Warning(
            level=WarningLevel.WARNING,
            message=f"Dropping table '{table_name}' will delete all its data.",
            context=f"Table: {table_name}"
        ))
        self.migration_steps.append(step)

    def _generate_create_table(self, table: Table):
        """
        Generate step to create a table.
        
        Args:
            table: Table object to create
        """
        sql_parts = [f"CREATE TABLE `{table.name}` ("]
        
        # Add column definitions
        column_defs = []
        for column in table.columns:
            col_def = f"  `{column.name}` {column.data_type}"
            
            if column.character_set:
                col_def += f" CHARACTER SET {column.character_set}"
            
            if column.collation:
                col_def += f" COLLATE {column.collation}"
            
            if not column.is_nullable:
                col_def += " NOT NULL"
            else:
                col_def += " NULL"
            
            if column.default is not None:
                col_def += f" DEFAULT {column.default}"
            
            if column.extra:
                col_def += f" {column.extra}"
            
            if column.comment:
                col_def += f" COMMENT '{column.comment}'"
            
            column_defs.append(col_def)
        
        sql_parts.append(",\n".join(column_defs))
        
        # Add primary key
        if table.primary_key:
            pk_cols = ", ".join(f"`{col}`" for col in table.primary_key)
            sql_parts.append(f",\n  PRIMARY KEY ({pk_cols})")
        
        # Add indexes
        for index in table.indexes:
            idx_cols = ", ".join(f"`{col}`" for col in index.columns)
            unique = "UNIQUE " if index.is_unique else ""
            sql_parts.append(f",\n  {unique}INDEX `{index.name}` ({idx_cols}) USING {index.index_type}")
        
        # Add foreign keys
        for fk in table.foreign_keys:
            fk_cols = ", ".join(f"`{col}`" for col in fk.columns)
            ref_cols = ", ".join(f"`{col}`" for col in fk.referenced_columns)
            sql_parts.append(
                f",\n  CONSTRAINT `{fk.name}` FOREIGN KEY ({fk_cols}) "
                f"REFERENCES `{fk.referenced_table}` ({ref_cols}) "
                f"ON DELETE {fk.on_delete} ON UPDATE {fk.on_update}"
            )
        
        sql_parts.append("\n)")
        
        # Add engine and charset
        sql_parts.append(f" ENGINE={table.engine}")
        if table.charset:
            sql_parts.append(f" DEFAULT CHARSET={table.charset}")
        if table.collation:
            sql_parts.append(f" COLLATE={table.collation}")
        if table.comment:
            sql_parts.append(f" COMMENT='{table.comment}'")
        
        sql_parts.append(";")
        
        step = MigrationStep(
            stage=MigrationStage.CREATE_TABLES,
            sql="".join(sql_parts),
            description=f"Create table '{table.name}'"
        )
        
        # Validate the table and attach warnings
        step.warnings.extend(SchemaValidator._validate_table(table))
        
        self.migration_steps.append(step)

    def _compare_table_structure(self, source_table: Table, dest_table: Table):
        """
        Compare the structure of two tables and generate modification steps.
        
        Args:
            source_table: Source table (target state)
            dest_table: Destination table (current state)
        """
        # First, handle foreign keys that need to be dropped
        self._compare_foreign_keys(source_table, dest_table)
        
        # Then compare indexes
        self._compare_indexes(source_table, dest_table)
        
        # Then compare columns
        self._compare_columns(source_table, dest_table)
        
        # Update table options if needed
        self._compare_table_options(source_table, dest_table)

    def _compare_columns(self, source_table: Table, dest_table: Table):
        """Compare columns between two tables."""
        source_cols = {col.name: col for col in source_table.columns}
        dest_cols = {col.name: col for col in dest_table.columns}
        
        source_col_names = set(source_cols.keys())
        dest_col_names = set(dest_cols.keys())
        
        # Columns to drop
        if self.destructive:
            for col_name in dest_col_names - source_col_names:
                step = MigrationStep(
                    stage=MigrationStage.DROP_COLUMNS,
                    sql=f"ALTER TABLE `{source_table.name}` DROP COLUMN `{col_name}`;",
                    description=f"Drop column '{col_name}' from table '{source_table.name}'"
                )
                step.warnings.append(Warning(
                    level=WarningLevel.WARNING,
                    message=f"Dropping column '{col_name}' will delete all its data.",
                    context=f"Table: {source_table.name}"
                ))
                self.migration_steps.append(step)
        
        # Columns to add
        for col_name in source_col_names - dest_col_names:
            column = source_cols[col_name]
            self._generate_add_column(source_table.name, column)
        
        # Columns to modify
        for col_name in source_col_names & dest_col_names:
            source_col = source_cols[col_name]
            dest_col = dest_cols[col_name]
            
            if source_col != dest_col:
                self._generate_modify_column(source_table.name, source_col, dest_col)

    def _generate_add_column(self, table_name: str, column: Column):
        """Generate step to add a column."""
        col_def = f"`{column.name}` {column.data_type}"
        
        if column.character_set:
            col_def += f" CHARACTER SET {column.character_set}"
        
        if column.collation:
            col_def += f" COLLATE {column.collation}"
        
        if not column.is_nullable:
            col_def += " NOT NULL"
        else:
            col_def += " NULL"
        
        if column.default is not None:
            col_def += f" DEFAULT {column.default}"
        
        if column.extra:
            col_def += f" {column.extra}"
        
        if column.comment:
            col_def += f" COMMENT '{column.comment}'"
        
        step = MigrationStep(
            stage=MigrationStage.ADD_COLUMNS,
            sql=f"ALTER TABLE `{table_name}` ADD COLUMN {col_def};",
            description=f"Add column '{column.name}' to table '{table_name}'"
        )
        
        # Check for potential issues
        if not column.is_nullable and column.default is None and 'auto_increment' not in column.extra.lower():
            step.warnings.append(Warning(
                level=WarningLevel.WARNING,
                message=f"Adding NOT NULL column '{column.name}' without a default value "
                       f"will fail if the table contains data.",
                context=f"Table: {table_name}"
            ))
        
        self.migration_steps.append(step)

    def _generate_modify_column(self, table_name: str, source_col: Column, dest_col: Column):
        """Generate step to modify a column."""
        col_def = f"`{source_col.name}` {source_col.data_type}"
        
        if source_col.character_set:
            col_def += f" CHARACTER SET {source_col.character_set}"
        
        if source_col.collation:
            col_def += f" COLLATE {source_col.collation}"
        
        if not source_col.is_nullable:
            col_def += " NOT NULL"
        else:
            col_def += " NULL"
        
        if source_col.default is not None:
            col_def += f" DEFAULT {source_col.default}"
        
        if source_col.extra:
            col_def += f" {source_col.extra}"
        
        if source_col.comment:
            col_def += f" COMMENT '{source_col.comment}'"
        
        step = MigrationStep(
            stage=MigrationStage.MODIFY_COLUMNS,
            sql=f"ALTER TABLE `{table_name}` MODIFY COLUMN {col_def};",
            description=f"Modify column '{source_col.name}' in table '{table_name}'"
        )
        
        # Check for potential data loss
        if self._is_lossy_column_change(dest_col, source_col):
            step.warnings.append(Warning(
                level=WarningLevel.WARNING,
                message=f"Changing column '{source_col.name}' from {dest_col.data_type} "
                       f"to {source_col.data_type} may cause data loss.",
                context=f"Table: {table_name}"
            ))
        
        # Check for nullable to not-nullable change
        if dest_col.is_nullable and not source_col.is_nullable:
            step.warnings.append(Warning(
                level=WarningLevel.WARNING,
                message=f"Changing column '{source_col.name}' from NULL to NOT NULL "
                       f"will fail if NULL values exist.",
                context=f"Table: {table_name}"
            ))
        
        self.migration_steps.append(step)

    def _is_lossy_column_change(self, old_col: Column, new_col: Column) -> bool:
        """
        Check if a column type change might cause data loss.
        
        Args:
            old_col: Current column definition
            new_col: New column definition
            
        Returns:
            True if the change might be lossy
        """
        # Extract base types and sizes
        old_type = old_col.data_type.upper()
        new_type = new_col.data_type.upper()
        
        # Check for VARCHAR/CHAR size reduction
        varchar_pattern = r'(VAR)?CHAR\((\d+)\)'
        old_match = re.match(varchar_pattern, old_type)
        new_match = re.match(varchar_pattern, new_type)
        
        if old_match and new_match:
            old_size = int(old_match.group(2))
            new_size = int(new_match.group(2))
            if new_size < old_size:
                return True
        
        # Check for numeric precision reduction
        decimal_pattern = r'DECIMAL\((\d+),(\d+)\)'
        old_match = re.match(decimal_pattern, old_type)
        new_match = re.match(decimal_pattern, new_type)
        
        if old_match and new_match:
            old_precision = int(old_match.group(1))
            new_precision = int(new_match.group(1))
            if new_precision < old_precision:
                return True
        
        # Check for type conversions that might lose data
        lossy_conversions = {
            'TEXT': ['VARCHAR', 'CHAR'],
            'BIGINT': ['INT', 'MEDIUMINT', 'SMALLINT', 'TINYINT'],
            'INT': ['MEDIUMINT', 'SMALLINT', 'TINYINT'],
            'FLOAT': ['DECIMAL'],
            'DOUBLE': ['FLOAT', 'DECIMAL'],
        }
        
        for from_type, to_types in lossy_conversions.items():
            if from_type in old_type:
                for to_type in to_types:
                    if to_type in new_type:
                        return True
        
        return False

    def _compare_indexes(self, source_table: Table, dest_table: Table):
        """Compare indexes between two tables."""
        source_indexes = {idx.name: idx for idx in source_table.indexes}
        dest_indexes = {idx.name: idx for idx in dest_table.indexes}
        
        source_idx_names = set(source_indexes.keys())
        dest_idx_names = set(dest_indexes.keys())
        
        # Indexes to drop
        if self.destructive:
            for idx_name in dest_idx_names - source_idx_names:
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.DROP_INDEXES,
                    sql=f"ALTER TABLE `{source_table.name}` DROP INDEX `{idx_name}`;",
                    description=f"Drop index '{idx_name}' from table '{source_table.name}'"
                ))
        
        # Indexes to create or modify
        for idx_name in source_idx_names:
            source_idx = source_indexes[idx_name]
            
            # If index doesn't exist in destination or is different, create it
            if idx_name not in dest_indexes or source_idx != dest_indexes[idx_name]:
                # Drop the old index if it exists and is different
                if idx_name in dest_indexes:
                    self.migration_steps.append(MigrationStep(
                        stage=MigrationStage.DROP_INDEXES,
                        sql=f"ALTER TABLE `{source_table.name}` DROP INDEX `{idx_name}`;",
                        description=f"Drop index '{idx_name}' from table '{source_table.name}' (will be recreated)"
                    ))
                
                # Create the new index
                idx_cols = ", ".join(f"`{col}`" for col in source_idx.columns)
                unique = "UNIQUE " if source_idx.is_unique else ""
                
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.CREATE_INDEXES,
                    sql=f"ALTER TABLE `{source_table.name}` ADD {unique}INDEX `{idx_name}` ({idx_cols}) USING {source_idx.index_type};",
                    description=f"Create index '{idx_name}' on table '{source_table.name}'"
                ))

    def _compare_foreign_keys(self, source_table: Table, dest_table: Table):
        """Compare foreign keys between two tables."""
        source_fks = {fk.name: fk for fk in source_table.foreign_keys}
        dest_fks = {fk.name: fk for fk in dest_table.foreign_keys}
        
        source_fk_names = set(source_fks.keys())
        dest_fk_names = set(dest_fks.keys())
        
        # Foreign keys to drop
        if self.destructive:
            for fk_name in dest_fk_names - source_fk_names:
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.DROP_FOREIGN_KEYS,
                    sql=f"ALTER TABLE `{source_table.name}` DROP FOREIGN KEY `{fk_name}`;",
                    description=f"Drop foreign key '{fk_name}' from table '{source_table.name}'"
                ))
        
        # Foreign keys to create or modify
        for fk_name in source_fk_names:
            source_fk = source_fks[fk_name]
            
            # If FK doesn't exist in destination or is different, create it
            if fk_name not in dest_fks or source_fk != dest_fks[fk_name]:
                # Drop the old FK if it exists and is different
                if fk_name in dest_fks:
                    self.migration_steps.append(MigrationStep(
                        stage=MigrationStage.DROP_FOREIGN_KEYS,
                        sql=f"ALTER TABLE `{source_table.name}` DROP FOREIGN KEY `{fk_name}`;",
                        description=f"Drop foreign key '{fk_name}' from table '{source_table.name}' (will be recreated)"
                    ))
                
                # Create the new FK
                fk_cols = ", ".join(f"`{col}`" for col in source_fk.columns)
                ref_cols = ", ".join(f"`{col}`" for col in source_fk.referenced_columns)
                
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.CREATE_FOREIGN_KEYS,
                    sql=f"ALTER TABLE `{source_table.name}` ADD CONSTRAINT `{fk_name}` "
                        f"FOREIGN KEY ({fk_cols}) REFERENCES `{source_fk.referenced_table}` ({ref_cols}) "
                        f"ON DELETE {source_fk.on_delete} ON UPDATE {source_fk.on_update};",
                    description=f"Create foreign key '{fk_name}' on table '{source_table.name}'"
                ))

    def _compare_table_options(self, source_table: Table, dest_table: Table):
        """Compare and update table-level options like engine, charset, etc."""
        changes = []
        
        if source_table.engine != dest_table.engine:
            changes.append(f"ENGINE={source_table.engine}")
        
        if source_table.charset and source_table.charset != dest_table.charset:
            changes.append(f"DEFAULT CHARSET={source_table.charset}")
        
        if source_table.collation and source_table.collation != dest_table.collation:
            changes.append(f"COLLATE={source_table.collation}")
        
        if source_table.comment != dest_table.comment:
            changes.append(f"COMMENT='{source_table.comment}'")
        
        if changes:
            sql = f"ALTER TABLE `{source_table.name}` {' '.join(changes)};"
            self.migration_steps.append(MigrationStep(
                stage=MigrationStage.MODIFY_COLUMNS,
                sql=sql,
                description=f"Update table options for '{source_table.name}'"
            ))

    def _compare_views(self):
        """Compare views between source and destination schemas."""
        source_views = set(self.source.views.keys())
        dest_views = set(self.destination.views.keys())
        
        # Views to drop
        if self.destructive:
            for view_name in dest_views - source_views:
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.DROP_VIEWS,
                    sql=f"DROP VIEW IF EXISTS `{view_name}`;",
                    description=f"Drop view '{view_name}'"
                ))
        
        # Views to create or replace
        for view_name in source_views:
            view = self.source.views[view_name]
            
            # Always use CREATE OR REPLACE for views
            self.migration_steps.append(MigrationStep(
                stage=MigrationStage.CREATE_VIEWS,
                sql=f"CREATE OR REPLACE VIEW `{view_name}` AS {view.definition};",
                description=f"Create or replace view '{view_name}'"
            ))

    def _compare_procedures(self):
        """Compare stored procedures between source and destination schemas."""
        source_procs = set(self.source.procedures.keys())
        dest_procs = set(self.destination.procedures.keys())
        
        # Procedures to create or replace
        for proc_name in source_procs:
            proc = self.source.procedures[proc_name]
            
            # Drop if it exists in destination and we're updating it
            if proc_name in dest_procs:
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.CREATE_PROCEDURES,
                    sql=f"DROP {proc.type} IF EXISTS `{proc_name}`;",
                    description=f"Drop {proc.type.lower()} '{proc_name}' (will be recreated)"
                ))
            
            # Create the procedure/function
            self.migration_steps.append(MigrationStep(
                stage=MigrationStage.CREATE_PROCEDURES,
                sql=proc.definition + ";",
                description=f"Create {proc.type.lower()} '{proc_name}'"
            ))

    def _compare_triggers(self):
        """Compare triggers between source and destination schemas."""
        source_triggers = set(self.source.triggers.keys())
        dest_triggers = set(self.destination.triggers.keys())
        
        # Triggers to drop
        if self.destructive:
            for trigger_name in dest_triggers - source_triggers:
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.DROP_TRIGGERS,
                    sql=f"DROP TRIGGER IF EXISTS `{trigger_name}`;",
                    description=f"Drop trigger '{trigger_name}'"
                ))
        
        # Triggers to create or replace
        for trigger_name in source_triggers:
            trigger = self.source.triggers[trigger_name]
            
            # Drop if it exists (MySQL doesn't support CREATE OR REPLACE for triggers)
            if trigger_name in dest_triggers:
                self.migration_steps.append(MigrationStep(
                    stage=MigrationStage.DROP_TRIGGERS,
                    sql=f"DROP TRIGGER IF EXISTS `{trigger_name}`;",
                    description=f"Drop trigger '{trigger_name}' (will be recreated)"
                ))
            
            # Create the trigger
            create_sql = (
                f"CREATE TRIGGER `{trigger_name}` {trigger.timing} {trigger.event} "
                f"ON `{trigger.table}` FOR EACH ROW {trigger.definition};"
            )
            
            self.migration_steps.append(MigrationStep(
                stage=MigrationStage.CREATE_TRIGGERS,
                sql=create_sql,
                description=f"Create trigger '{trigger_name}'"
            ))


# ============================================================================
# JSON SCHEMA SERIALIZATION
# ============================================================================

class SchemaSerializer:
    """
    Handles serialization and deserialization of Schema objects to/from JSON.
    """

    @staticmethod
    def schema_to_json(schema: Schema) -> str:
        """
        Convert a Schema object to JSON string.
        
        Args:
            schema: Schema to serialize
            
        Returns:
            JSON string representation
        """
        def convert_to_dict(obj):
            """Recursively convert dataclass objects to dictionaries."""
            if hasattr(obj, '__dataclass_fields__'):
                return {
                    key: convert_to_dict(value)
                    for key, value in asdict(obj).items()
                }
            elif isinstance(obj, dict):
                return {key: convert_to_dict(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_dict(item) for item in obj]
            else:
                return obj
        
        schema_dict = convert_to_dict(schema)
        return json.dumps(schema_dict, indent=2)

    @staticmethod
    def json_to_schema(json_str: str) -> Schema:
        """
        Convert JSON string to Schema object.
        
        Args:
            json_str: JSON string to deserialize
            
        Returns:
            Schema object
        """
        data = json.loads(json_str)
        schema = Schema(database_name=data.get('database_name', ''))
        
        # Deserialize tables
        for table_name, table_data in data.get('tables', {}).items():
            table = Table(name=table_name)
            
            # Deserialize columns
            table.columns = [
                Column(**col_data) for col_data in table_data.get('columns', [])
            ]
            
            # Deserialize other table properties
            table.primary_key = table_data.get('primary_key', [])
            table.engine = table_data.get('engine', 'InnoDB')
            table.charset = table_data.get('charset')
            table.collation = table_data.get('collation')
            table.comment = table_data.get('comment', '')
            
            # Deserialize indexes
            table.indexes = [
                Index(**idx_data) for idx_data in table_data.get('indexes', [])
            ]
            
            # Deserialize foreign keys
            table.foreign_keys = [
                ForeignKey(**fk_data) for fk_data in table_data.get('foreign_keys', [])
            ]
            
            schema.tables[table_name] = table
        
        # Deserialize views
        for view_name, view_data in data.get('views', {}).items():
            schema.views[view_name] = View(**view_data)
        
        # Deserialize procedures
        for proc_name, proc_data in data.get('procedures', {}).items():
            schema.procedures[proc_name] = StoredProcedure(**proc_data)
        
        # Deserialize triggers
        for trigger_name, trigger_data in data.get('triggers', {}).items():
            schema.triggers[trigger_name] = Trigger(**trigger_data)
        
        return schema


# ============================================================================
# CLI INTERFACE
# ============================================================================

def parse_connection_string(conn_str: str) -> Dict[str, Any]:
    """
    Parse a MySQL connection string.
    
    Format: user:password@host:port/database
    
    Args:
        conn_str: Connection string
        
    Returns:
        Dictionary with connection parameters
    """
    pattern = r'(?:([^:@]+)(?::([^@]+))?@)?([^:/@]+)(?::(\d+))?/(.+)'
    match = re.match(pattern, conn_str)
    
    if not match:
        print(f"Error: Invalid connection string format: {conn_str}", file=sys.stderr)
        print("Expected format: user:password@host:port/database", file=sys.stderr)
        sys.exit(1)
    
    user, password, host, port, database = match.groups()
    
    return {
        'user': user or 'root',
        'password': password or '',
        'host': host,
        'port': int(port) if port else 3306,
        'database': database
    }


def export_command(args):
    """
    Handle the export command.
    
    Args:
        args: Parsed command-line arguments
    """
    # Parse connection string
    conn_params = parse_connection_string(args.source)
    
    # Connect to database and extract schema
    print(f"Connecting to database '{conn_params['database']}' on {conn_params['host']}...", file=sys.stderr)
    
    with DatabaseConnection(**conn_params) as db:
        schema = db.extract_schema(
            include_tables=args.include_tables,
            include_views=args.include_views,
            include_procedures=args.include_procedures,
            include_triggers=args.include_triggers
        )
    
    print(f"Schema extracted successfully.", file=sys.stderr)
    
    # Validate schema and show warnings
    warnings = SchemaValidator.validate_schema(schema)
    if warnings:
        print(f"\nFound {len(warnings)} warning(s):", file=sys.stderr)
        for warning in warnings:
            print(f"  [{warning.level.value}] {warning.message}", file=sys.stderr)
            if warning.context:
                print(f"    Context: {warning.context}", file=sys.stderr)
    
    # Serialize to JSON
    json_output = SchemaSerializer.schema_to_json(schema)
    
    # Output to file or stdout
    if args.output:
        with open(args.output, 'w') as f:
            f.write(json_output)
        print(f"\nSchema exported to: {args.output}", file=sys.stderr)
    else:
        print(json_output)


def migrate_command(args):
    """
    Handle the migrate command.
    
    Args:
        args: Parsed command-line arguments
    """
    # Load source schema (from database or JSON)
    if args.source.endswith('.json'):
        print(f"Loading source schema from JSON file: {args.source}", file=sys.stderr)
        with open(args.source, 'r') as f:
            source_schema = SchemaSerializer.json_to_schema(f.read())
    else:
        source_conn = parse_connection_string(args.source)
        print(f"Extracting source schema from database '{source_conn['database']}'...", file=sys.stderr)
        with DatabaseConnection(**source_conn) as db:
            source_schema = db.extract_schema(
                include_tables=args.include_tables,
                include_views=args.include_views,
                include_procedures=args.include_procedures,
                include_triggers=args.include_triggers
            )
    
    # Load destination schema (always from database)
    dest_conn = parse_connection_string(args.destination)
    print(f"Extracting destination schema from database '{dest_conn['database']}'...", file=sys.stderr)
    with DatabaseConnection(**dest_conn) as db:
        dest_schema = db.extract_schema(
            include_tables=args.include_tables,
            include_views=args.include_views,
            include_procedures=args.include_procedures,
            include_triggers=args.include_triggers
        )
    
    # Generate migration plan
    print("Analyzing schema differences...", file=sys.stderr)
    comparator = SchemaComparator(source_schema, dest_schema, destructive=args.destructive)
    migration_steps = comparator.generate_migration_plan(
        include_tables=args.include_tables,
        include_views=args.include_views,
        include_procedures=args.include_procedures,
        include_triggers=args.include_triggers
    )
    
    if not migration_steps:
        print("\nNo migration steps needed. Schemas are identical.", file=sys.stderr)
        return
    
    print(f"\nGenerated {len(migration_steps)} migration step(s).", file=sys.stderr)
    
    # Collect all warnings
    all_warnings = []
    for step in migration_steps:
        all_warnings.extend(step.warnings)
    
    # Display warnings
    if all_warnings:
        print(f"\nFound {len(all_warnings)} warning(s):", file=sys.stderr)
        for warning in all_warnings:
            print(f"  [{warning.level.value}] {warning.message}", file=sys.stderr)
            if warning.context:
                print(f"    Context: {warning.context}", file=sys.stderr)
        
        # Stop if warnings exist and --force not specified
        if not args.force:
            print("\nMigration stopped due to warnings. Use --force to proceed anyway.", file=sys.stderr)
            sys.exit(1)
        else:
            print("\nProceeding despite warnings (--force specified).", file=sys.stderr)
    
    # Generate SQL script if --plan specified
    if args.plan:
        sql_lines = ["-- MySQL Schema Migration Script", "-- Generated by MySQL Schema Migrator\n"]
        
        for step in migration_steps:
            sql_lines.append(f"-- {step.description}")
            if step.warnings:
                for warning in step.warnings:
                    sql_lines.append(f"-- WARNING: {warning.message}")
            sql_lines.append(step.sql)
            sql_lines.append("")
        
        sql_script = "\n".join(sql_lines)
        
        # Output to file or stdout
        if args.output:
            with open(args.output, 'w') as f:
                f.write(sql_script)
            print(f"\nMigration plan saved to: {args.output}", file=sys.stderr)
        else:
            print(sql_script)
    
    # Execute migration if --execute specified
    if args.execute:
        print("\nExecuting migration...", file=sys.stderr)
        
        with DatabaseConnection(**dest_conn) as db:
            cursor = db.connection.cursor()
            
            try:
                for i, step in enumerate(migration_steps, 1):
                    print(f"  [{i}/{len(migration_steps)}] {step.description}...", file=sys.stderr)
                    cursor.execute(step.sql)
                
                db.connection.commit()
                print("\nMigration completed successfully!", file=sys.stderr)
                
            except MySQLError as e:
                db.connection.rollback()
                print(f"\nError during migration: {e}", file=sys.stderr)
                sys.exit(1)
            finally:
                cursor.close()


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="MySQL Schema Migration Tool - Export, compare, and migrate MySQL database schemas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export schema to JSON
  %(prog)s export user:pass@localhost:3306/mydb -o schema.json

  # Generate migration plan (DB to DB)
  %(prog)s migrate user:pass@localhost:3306/source_db user:pass@localhost:3306/dest_db --plan

  # Execute migration from JSON to database
  %(prog)s migrate schema.json user:pass@localhost:3306/dest_db --execute --force

  # Non-destructive migration (won't drop anything)
  %(prog)s migrate source.json user:pass@localhost:3306/dest_db --execute

  # Destructive migration (makes destination exactly match source)
  %(prog)s migrate source.json user:pass@localhost:3306/dest_db --execute --destructive
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export database schema to JSON')
    export_parser.add_argument('source', help='Database connection string (user:pass@host:port/database)')
    export_parser.add_argument('-o', '--output', help='Output JSON file (default: stdout)')
    export_parser.add_argument('--no-tables', dest='include_tables', action='store_false', 
                              help='Exclude tables from export')
    export_parser.add_argument('--no-views', dest='include_views', action='store_false',
                              help='Exclude views from export')
    export_parser.add_argument('--no-procedures', dest='include_procedures', action='store_false',
                              help='Exclude stored procedures from export')
    export_parser.add_argument('--no-triggers', dest='include_triggers', action='store_false',
                              help='Exclude triggers from export')
    
    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Migrate schema from source to destination')
    migrate_parser.add_argument('source', 
                               help='Source: database connection string or JSON file')
    migrate_parser.add_argument('destination',
                               help='Destination: database connection string')
    migrate_parser.add_argument('--plan', action='store_true',
                               help='Generate SQL migration script')
    migrate_parser.add_argument('--execute', action='store_true',
                               help='Execute the migration')
    migrate_parser.add_argument('--force', action='store_true',
                               help='Proceed even if warnings are generated')
    migrate_parser.add_argument('--destructive', action='store_true',
                               help='Drop items not in source schema')
    migrate_parser.add_argument('-o', '--output', help='Output file for migration plan (default: stdout)')
    migrate_parser.add_argument('--no-tables', dest='include_tables', action='store_false',
                               help='Exclude tables from migration')
    migrate_parser.add_argument('--no-views', dest='include_views', action='store_false',
                               help='Exclude views from migration')
    migrate_parser.add_argument('--no-procedures', dest='include_procedures', action='store_false',
                               help='Exclude stored procedures from migration')
    migrate_parser.add_argument('--no-triggers', dest='include_triggers', action='store_false',
                               help='Exclude triggers from migration')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute the appropriate command
    if args.command == 'export':
        export_command(args)
    elif args.command == 'migrate':
        migrate_command(args)


if __name__ == '__main__':
    main()
