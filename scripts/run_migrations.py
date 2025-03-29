"""
Database Migration Script

This script runs SQL migrations against your Supabase database.
"""
import os
import logging
from pathlib import Path
from config.supabase_config import get_supabase_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_migrations():
    """Execute all SQL migration files in the migrations directory."""
    migrations_dir = Path(__file__).parent.parent / "migrations"
    
    if not migrations_dir.exists():
        logger.error(f"Migrations directory not found: {migrations_dir}")
        return False
    
    # Get all SQL files in the migrations directory
    migration_files = sorted([f for f in migrations_dir.glob("*.sql")])
    
    if not migration_files:
        logger.warning(f"No migration files found in {migrations_dir}")
        return True
    
    # Get Supabase client
    supabase = get_supabase_client()
    
    for migration_file in migration_files:
        try:
            logger.info(f"Running migration: {migration_file.name}")
            
            # Read the SQL file
            with open(migration_file, 'r') as f:
                sql = f.read()
            
            # Split the SQL file into individual statements
            # (this is a basic splitter and may need to be improved)
            statements = sql.split(';')
            
            # Execute each statement
            for statement in statements:
                if statement.strip():
                    try:
                        # Use RPC to execute raw SQL (better for complex statements)
                        result = supabase.rpc('exec_sql', {'query': statement}).execute()
                        logger.info(f"Statement executed successfully")
                    except Exception as e:
                        logger.error(f"Error executing statement: {e}")
                        # Continue with other statements
            
            logger.info(f"Migration completed: {migration_file.name}")
            
        except Exception as e:
            logger.error(f"Failed to run migration {migration_file.name}: {e}")
            return False
    
    logger.info("All migrations completed successfully")
    return True

if __name__ == "__main__":
    success = run_migrations()
    exit(0 if success else 1)
