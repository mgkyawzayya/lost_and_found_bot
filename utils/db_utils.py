import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

# Load environment variables
load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)

# Database connection
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "lost_and_found")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# Initialize Base
Base = declarative_base()

# Define models
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    reports = relationship("Report", back_populates="user")
    
class Report(Base):
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True)
    report_id = Column(String(10), unique=True, nullable=False)
    report_type = Column(String(50), nullable=False)
    details = Column(Text, nullable=False)
    urgency = Column(String(50), nullable=False)
    photo_file_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="reports")

# Create engine and session
try:
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("Database connection established")
except Exception as e:
    logger.error(f"Failed to create database engine: {str(e)}")
    # Fallback to SQLite for development/testing
    DATABASE_URL = "sqlite:///./lost_and_found.db"
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.warning("Using SQLite as fallback database")

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        logger.error(f"Error getting database session: {str(e)}")
        db.close()
        raise

def save_report(report_data, telegram_user):
    """Save report to database."""
    db = get_db()
    try:
        # Check if user exists, create if not
        user = db.query(User).filter(User.telegram_id == telegram_user.id).first()
        if not user:
            user = User(
                telegram_id=telegram_user.id,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                username=telegram_user.username
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        # Create report
        report = Report(
            report_id=report_data['report_id'],
            report_type=report_data['report_type'],
            details=report_data['all_data'],
            urgency=report_data['urgency'],
            photo_file_id=report_data.get('photo'),
            user_id=user.id
        )
        
        db.add(report)
        db.commit()
        logger.info(f"Report {report.report_id} saved successfully")
        return report
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error saving report: {str(e)}")
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving report: {str(e)}")
        raise
    finally:
        db.close()

def get_report_by_id(report_id):
    """Get report by ID."""
    db = get_db()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        return report
    except Exception as e:
        logger.error(f"Error retrieving report: {str(e)}")
        return None
    finally:
        db.close()

# Add this function to your existing db_utils.py

def search_reports_by_content(search_query, report_type=None):
    """Search reports by content."""
    try:
        # Adjust this query based on your actual database schema
        # This is a basic example assuming you have a Reports table
        query = "SELECT report_id, details, user_id, created_at FROM reports WHERE details LIKE %s"
        params = [f"%{search_query}%"]
        
        if report_type:
            query += " AND report_type = %s"
            params.append(report_type)
            
        # Execute query and fetch results
        # This implementation depends on your database connection
        # Below is a mock implementation - replace with your actual database code
        
        # For example using psycopg2:
        # from db import get_db_connection
        # conn = get_db_connection()
        # cursor = conn.cursor()
        # cursor.execute(query, params)
        # results = cursor.fetchall()
        # cursor.close()
        # conn.close()
        
        # For now, let's return an empty list since this is a stub
        # In reality, you'd return results from your database
        logger.warning("Using mock implementation of search_reports_by_content")
        return []
        
    except Exception as e:
        logger.error(f"Error searching reports by content: {str(e)}")
        return []

def init_db():
    """Initialize database tables"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise
