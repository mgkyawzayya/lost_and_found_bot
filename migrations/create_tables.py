import sys
import os
import logging

# Add parent directory to path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import init_db
from models.report import Base

def run_migration():
    """Run database migration to create tables"""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Creating database tables...")
        init_db()
        logger.info("Database tables created successfully!")
    except Exception as e:
        logger.error(f"Error creating tables: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
