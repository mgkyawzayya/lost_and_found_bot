import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from supabase import create_client, Client
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import re
from urllib.parse import urlparse
import io
import uuid
import socket
import time

# Load environment variables from .env file if present
load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

# Function to extract PostgreSQL host from Supabase URL
def extract_pg_host_from_supabase_url(url: str) -> str:
    """Extract the PostgreSQL host from a Supabase URL"""
    if not url:
        return ""
    
    try:
        # Parse the URL
        parsed_url = urlparse(url)
        hostname = parsed_url.netloc
        
        # If the hostname starts with "db.", use it directly
        if hostname.startswith("db."):
            return hostname
        
        # Otherwise, prepend "db." to the hostname
        project_ref = hostname.split('.')[0]
        return f"db.{project_ref}.supabase.co"
    except Exception as e:
        logger.error(f"Failed to extract PostgreSQL host from Supabase URL: {str(e)}")
        return ""

# PostgreSQL connection details
pg_user = os.environ.get("POSTGRES_USER", "postgres")
pg_password = os.environ.get("POSTGRES_PASSWORD", "")
pg_host = os.environ.get("POSTGRES_HOST", "")
# If pg_host is not explicitly set, try to extract it from Supabase URL
if not pg_host and supabase_url:
    pg_host = extract_pg_host_from_supabase_url(supabase_url)
pg_port = os.environ.get("POSTGRES_PORT", "5432")
pg_database = os.environ.get("POSTGRES_DB", "postgres")
pg_schema = os.environ.get("POSTGRES_SCHEMA", "public")
pg_table = os.environ.get("POSTGRES_TABLE", "reports")

# Global variables to track if connections are ready
db_ready = False
pg_conn = None
REPORTS = {}  # In-memory storage for reports when DB is unavailable

# Initialize Supabase connection
if not supabase_url or not supabase_key:
    logger.warning("Supabase credentials not found in environment variables. Check your .env file or environment setup.")
    supabase = None
else:
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully")
        db_ready = True
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {str(e)}")
        supabase = None

# Function to ensure the required database schema is present
def ensure_schema_exists():
    """Check if all required columns exist and create them if they don't"""
    if not is_db_ready():
        logger.warning("Database not ready, cannot verify schema")
        return False
    
    try:
        # Try to create the photo_url column if it doesn't exist
        # Using RPC is the safest way to do this through the Supabase API
        # Note: You need to create this function in your Supabase database first
        try:
            supabase.rpc('add_column_if_not_exists', {
                'table_name': pg_table,
                'column_name': 'photo_url',
                'column_type': 'TEXT'
            }).execute()
            logger.info("Verified 'photo_url' column exists in schema")
            return True
        except Exception as e:
            logger.warning(f"Could not use RPC to add column: {str(e)}")
            
            # Fall back to direct PostgreSQL connection
            conn = get_postgres_connection(direct_connect=True)
            if conn is None:
                logger.error("Could not establish PostgreSQL connection to update schema")
                return False
            
            cursor = conn.cursor()
            
            # Add photo_url column if it doesn't exist
            query = f"""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_schema = '{pg_schema}'
                    AND table_name = '{pg_table}' 
                    AND column_name = 'photo_url'
                ) THEN 
                    ALTER TABLE {pg_schema}.{pg_table} ADD COLUMN photo_url TEXT;
                END IF;
            END $$;
            """
            
            cursor.execute(query)
            conn.commit()
            cursor.close()
            
            logger.info("Added 'photo_url' column to database schema if it didn't exist")
            return True
            
    except Exception as e:
        logger.error(f"Error ensuring schema exists: {str(e)}")
        return False

# Function to check DNS resolution before attempting connection
def check_host_dns_resolution(hostname):
    """
    Check if a hostname can be resolved to an IP address
    
    Args:
        hostname: The hostname to check
        
    Returns:
        Tuple of (is_resolvable, message) where is_resolvable is a boolean and message contains details
    """
    try:
        logger.debug(f"Checking DNS resolution for: {hostname}")
        ip_address = socket.gethostbyname(hostname)
        return True, f"Hostname {hostname} resolves to {ip_address}"
    except socket.gaierror as e:
        return False, f"DNS resolution failed for {hostname}: {e}"
    except Exception as e:
        return False, f"Error checking DNS resolution for {hostname}: {e}"

# Initialize PostgreSQL connection
def get_postgres_connection(direct_connect=False, max_retries=3, retry_delay=2):
    """
    Create and return a PostgreSQL connection with retry capability
    
    Args:
        direct_connect: If True, attempt to connect using direct PostgreSQL connection parameters
                        from environment variables instead of deriving from Supabase URL
        max_retries: Maximum number of connection attempts
        retry_delay: Initial delay between retries in seconds (will be doubled after each retry)
        
    Returns:
        A PostgreSQL connection or None if connection failed
    """
    global pg_conn
    
    if pg_conn is not None:
        try:
            # Test if connection is still alive
            pg_conn.cursor().execute("SELECT 1")
            return pg_conn
        except Exception:
            # Connection is dead, create a new one
            logger.info("Existing PostgreSQL connection is no longer valid, creating a new one")
            pg_conn = None
    
    # If direct connection is requested, try to use explicit connection parameters
    if direct_connect:
        direct_host = os.environ.get("DIRECT_PG_HOST", "")
        direct_port = os.environ.get("DIRECT_PG_PORT", "5432")
        direct_user = os.environ.get("DIRECT_PG_USER", pg_user)
        direct_password = os.environ.get("DIRECT_PG_PASSWORD", pg_password)
        direct_database = os.environ.get("DIRECT_PG_DATABASE", pg_database)
        
        if direct_host:
            logger.info(f"Attempting direct PostgreSQL connection to: {direct_host}")
            
            # Check DNS resolution first
            resolvable, message = check_host_dns_resolution(direct_host)
            if not resolvable:
                logger.error(f"DNS resolution check failed: {message}")
                logger.info("Will attempt connection anyway, but it's likely to fail")
            else:
                logger.info(message)
            
            # Try to connect with retry mechanism
            retry_count = 0
            current_delay = retry_delay
            
            while retry_count <= max_retries:
                try:
                    pg_conn = psycopg2.connect(
                        user=direct_user,
                        password=direct_password,
                        host=direct_host,
                        port=direct_port,
                        database=direct_database,
                        connect_timeout=10
                    )
                    logger.info("Direct PostgreSQL connection established successfully")
                    return pg_conn
                except psycopg2.OperationalError as e:
                    error_msg = str(e).lower()
                    retry_count += 1
                    
                    if "could not translate host name" in error_msg or "name or service not known" in error_msg:
                        logger.error(f"DNS resolution error on attempt {retry_count}/{max_retries}: {e}")
                        if retry_count <= max_retries:
                            logger.info(f"Retrying in {current_delay} seconds...")
                            time.sleep(current_delay)
                            current_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"Failed to resolve host after {max_retries} attempts")
                    elif "timeout" in error_msg:
                        logger.error(f"Connection timeout on attempt {retry_count}/{max_retries}: {e}")
                        if retry_count <= max_retries:
                            logger.info(f"Retrying in {current_delay} seconds...")
                            time.sleep(current_delay)
                            current_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"Connection timed out after {max_retries} attempts")
                    else:
                        logger.error(f"Failed to connect with direct PostgreSQL connection: {e}")
                        break  # Don't retry for other errors
                except Exception as e:
                    logger.error(f"Unexpected error during PostgreSQL connection: {e}")
                    break  # Don't retry for unexpected errors
    
    # Verify we have all the required connection parameters
    if not pg_host:
        logger.error("PostgreSQL host is not set. Check your environment variables or Supabase URL.")
        return None
        
    if not pg_password:
        logger.error("PostgreSQL password is not set. Check your environment variables.")
        return None
    
    # Check DNS resolution before attempting connection
    resolvable, message = check_host_dns_resolution(pg_host)
    if not resolvable:
        logger.error(f"DNS resolution check failed: {message}")
        logger.error("Please check your network connection and DNS settings")
        logger.error(f"The host name '{pg_host}' cannot be resolved to an IP address")
        logger.info("Will attempt connection anyway, but it's likely to fail")
    else:
        logger.info(message)
    
    # Log connection attempt for debugging
    logger.info(f"Attempting to connect to PostgreSQL at host: {pg_host}")
    
    # Try to connect with retry mechanism
    retry_count = 0
    current_delay = retry_delay
    
    while retry_count <= max_retries:
        try:
            # Create a new connection with a timeout to avoid hanging
            pg_conn = psycopg2.connect(
                user=pg_user,
                password=pg_password,
                host=pg_host,
                port=pg_port,
                database=pg_database,
                connect_timeout=10  # Add a timeout to avoid hanging
            )
            logger.info("PostgreSQL connection established successfully")
            return pg_conn
        except psycopg2.OperationalError as e:
            error_msg = str(e).lower()
            retry_count += 1
            
            if "could not translate host name" in error_msg or "name or service not known" in error_msg:
                logger.error(f"DNS resolution error on attempt {retry_count}/{max_retries}: {e}")
                if retry_count <= max_retries:
                    logger.info(f"Retrying in {current_delay} seconds...")
                    time.sleep(current_delay)
                    current_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to resolve host after {max_retries} attempts")
            elif "timeout" in error_msg:
                logger.error(f"Connection timeout on attempt {retry_count}/{max_retries}: {e}")
                if retry_count <= max_retries:
                    logger.info(f"Retrying in {current_delay} seconds...")
                    time.sleep(current_delay)
                    current_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Connection timed out after {max_retries} attempts")
            else:
                logger.error(f"Failed to connect to PostgreSQL: {e}")
                break  # Don't retry for other errors
        except Exception as e:
            logger.error(f"Unexpected error during PostgreSQL connection: {e}")
            break  # Don't retry for unexpected errors
    
    return None

def is_db_ready() -> bool:
    """Check if the database client is initialized and ready"""
    return db_ready and supabase is not None

def upload_photo_to_storage(photo_data: Union[str, bytes, io.BytesIO], file_name: Optional[str] = None) -> Optional[str]:
    """
    Upload a photo to Supabase Storage and return the public URL.
    
    Args:
        photo_data: The photo data (file path, bytes, or BytesIO object)
        file_name: Optional file name to use, otherwise a UUID will be generated
        
    Returns:
        Public URL of the uploaded file or None if upload failed
    """
    if not is_db_ready():
        logger.error("Database not ready, cannot upload photo")
        return None
        
    try:
        # Generate a unique file name if not provided
        if not file_name:
            file_name = f"{uuid.uuid4()}.jpg"
            
        bucket_name = os.environ.get("SUPABASE_STORAGE_BUCKET", "reports-photos")
        
        # Handle different input types
        if isinstance(photo_data, str) and os.path.isfile(photo_data):
            # If photo_data is a file path
            with open(photo_data, 'rb') as f:
                file_data = f.read()
        elif isinstance(photo_data, bytes):
            # If photo_data is already bytes
            file_data = photo_data
        elif isinstance(photo_data, io.BytesIO):
            # If photo_data is a BytesIO object
            file_data = photo_data.getvalue()
        else:
            logger.error(f"Unsupported photo data type: {type(photo_data)}")
            return None
            
        # Create the bucket if it doesn't exist
        try:
            supabase.storage.create_bucket(bucket_name)
        except Exception as e:
            # Bucket might already exist, which is fine
            pass
            
        # Upload the file
        response = supabase.storage.from_(bucket_name).upload(
            path=file_name,
            file=file_data,
            file_options={"content-type": "image/jpeg", "upsert": True}
        )
        
        # Get the public URL
        file_url = supabase.storage.from_(bucket_name).get_public_url(file_name)
        
        logger.info(f"Photo uploaded successfully: {file_url}")
        return file_url
    
    except Exception as e:
        logger.error(f"Error uploading photo to storage: {str(e)}")
        return None

def save_report(report_data: Dict[str, Any], telegram_user: Any) -> Optional[Dict[str, Any]]:
    """Save a report to the database"""
    # Ensure the schema exists with all required columns
    ensure_schema_exists()
    
    # Try using the Supabase REST API first
    try:
        if is_db_ready():
            # Handle photo upload if present
            photo_url = None
            if report_data.get("photo"):
                photo_data = report_data["photo"]
                # Generate a unique filename based on report ID
                filename = f"{report_data['report_id']}.jpg"
                photo_url = upload_photo_to_storage(photo_data, filename)
                
            # Prepare data for database
            db_data = {
                "report_id": report_data["report_id"],
                "report_type": report_data["report_type"],
                "all_data": report_data["all_data"],
                "urgency": report_data["urgency"],
                "photo_id": report_data["photo"]  # Keep original photo_id for backward compatibility
            }
            
            # Only add photo_url if we have it
            if photo_url:
                db_data["photo_url"] = photo_url
                
            # Add user information
            db_data.update({
                "user_id": telegram_user.id,
                "username": telegram_user.username,
                "first_name": telegram_user.first_name,
                "last_name": telegram_user.last_name,
                "location": report_data.get("location", "Unknown"),
                "created_at": datetime.now().isoformat()
            })
            
            # Insert into database using Supabase
            response = supabase.table(pg_table).insert(db_data).execute()
            
            if len(response.data) > 0:
                logger.info(f"Report saved successfully with ID: {report_data['report_id']} via Supabase")
                return response.data[0]
    except Exception as e:
        logger.warning(f"Error saving report via Supabase: {str(e)}. Trying direct PostgreSQL connection...")
    
    # Fall back to direct PostgreSQL connection if Supabase fails
    try:
        # Try with direct connection parameters first
        conn = get_postgres_connection(direct_connect=True)
        if conn is None:
            logger.error("Could not establish PostgreSQL connection")
            # Save to in-memory storage as a last resort
            REPORTS[report_data["report_id"]] = {
                "report_id": report_data["report_id"],
                "report_type": report_data["report_type"],
                "all_data": report_data["all_data"],
                "urgency": report_data["urgency"],
                "photo_id": report_data["photo"],
                "user_id": telegram_user.id,
                "username": telegram_user.username,
                "first_name": telegram_user.first_name,
                "last_name": telegram_user.last_name,
                "location": report_data.get("location", "Unknown"),
                "created_at": datetime.now().isoformat()
            }
            logger.info(f"Report stored in memory: {report_data['report_id']}")
            return REPORTS[report_data["report_id"]]
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Prepare data for PostgreSQL
        now = datetime.now().isoformat()
        
        # Try to upload photo if we have Supabase but the earlier attempt failed
        photo_url = None
        if is_db_ready() and report_data.get("photo"):
            photo_data = report_data["photo"]
            filename = f"{report_data['report_id']}.jpg"
            photo_url = upload_photo_to_storage(photo_data, filename)
        
        # Check if photo_url column exists
        try:
            cursor.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = '{pg_schema}' AND table_name = '{pg_table}' AND column_name = 'photo_url'
            """)
            has_photo_url = cursor.fetchone() is not None
        except Exception:
            has_photo_url = False
        
        # Construct SQL based on column existence
        if has_photo_url:
            # SQL query with photo_url
            query = f"""
            INSERT INTO {pg_schema}.{pg_table} 
            (report_id, report_type, all_data, urgency, photo_id, photo_url, user_id, username, first_name, last_name, 
            location, created_at, updated_at) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
            """
            params = (
                report_data["report_id"],
                report_data["report_type"],
                report_data["all_data"],
                report_data["urgency"],
                report_data["photo"],
                photo_url,
                telegram_user.id,
                telegram_user.username,
                telegram_user.first_name,
                telegram_user.last_name,
                report_data.get("location", "Unknown"),
                now,
                now
            )
        else:
            # SQL query without photo_url
            query = f"""
            INSERT INTO {pg_schema}.{pg_table} 
            (report_id, report_type, all_data, urgency, photo_id, user_id, username, first_name, last_name, 
            location, created_at, updated_at) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
            """
            params = (
                report_data["report_id"],
                report_data["report_type"],
                report_data["all_data"],
                report_data["urgency"],
                report_data["photo"],
                telegram_user.id,
                telegram_user.username,
                telegram_user.first_name,
                telegram_user.last_name,
                report_data.get("location", "Unknown"),
                now,
                now
            )
        
        # Execute the query with parameters
        cursor.execute(query, params)
        
        # Commit the transaction
        conn.commit()
        
        # Get the inserted row
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            logger.info(f"Report saved successfully with ID: {report_data['report_id']} via PostgreSQL")
            return dict(result)
        else:
            logger.error("No data returned from PostgreSQL after insert")
            # Save to in-memory storage as a last resort
            REPORTS[report_data["report_id"]] = {
                "report_id": report_data["report_id"],
                "report_type": report_data["report_type"],
                "all_data": report_data["all_data"],
                "urgency": report_data["urgency"],
                "photo_id": report_data["photo"],
                "user_id": telegram_user.id,
                "username": telegram_user.username,
                "first_name": telegram_user.first_name,
                "last_name": telegram_user.last_name,
                "location": report_data.get("location", "Unknown"),
                "created_at": now
            }
            logger.info(f"Report stored in memory: {report_data['report_id']}")
            return REPORTS[report_data["report_id"]]
            
    except Exception as e:
        logger.error(f"Error saving report to PostgreSQL database: {str(e)}")
        # Save to in-memory storage as a last resort
        REPORTS[report_data["report_id"]] = {
            "report_id": report_data["report_id"],
            "report_type": report_data["report_type"],
            "all_data": report_data["all_data"],
            "urgency": report_data["urgency"],
            "photo_id": report_data["photo"],
            "user_id": telegram_user.id,
            "username": telegram_user.username,
            "first_name": telegram_user.first_name,
            "last_name": telegram_user.last_name,
            "location": report_data.get("location", "Unknown"),
            "created_at": datetime.now().isoformat()
        }
        logger.info(f"Report stored in memory: {report_data['report_id']}")
        return REPORTS[report_data["report_id"]]

async def get_report_by_id(report_id: str):
    """Get a report by its ID."""
    try:
        # Try using existing Supabase client first
        if is_db_ready():
            response = supabase.table(pg_table).select('*').eq('report_id', report_id).execute()
            
            if response and hasattr(response, 'data') and len(response.data) > 0:
                logger.info(f"Report found with ID: {report_id} via Supabase")
                return response.data[0]
        
        # Fall back to direct PostgreSQL connection
        conn = get_postgres_connection()
        if conn is None:
            logger.error("Could not establish PostgreSQL connection")
            # Check in-memory storage as last resort
            if REPORTS and report_id in REPORTS:
                logger.info(f"Report found with ID: {report_id} in memory storage")
                return REPORTS[report_id]
            return None
            
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # SQL query to get the report
        query = f"""
        SELECT * FROM {pg_schema}.{pg_table}
        WHERE report_id = %s;
        """
        
        # Execute the query
        cursor.execute(query, (report_id,))
        
        # Get the result
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            logger.info(f"Report found with ID: {report_id} via PostgreSQL")
            return dict(result)
        
        # If no results from database, check in-memory storage
        if REPORTS and report_id in REPORTS:
            logger.info(f"Report found with ID: {report_id} in memory storage")
            return REPORTS[report_id]
            
        logger.info(f"No report found with ID: {report_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching report by ID: {str(e)}")
        # Check in-memory storage as last resort after exception
        if REPORTS and report_id in REPORTS:
            logger.info(f"Report found with ID: {report_id} in memory storage after DB error")
            return REPORTS[report_id]
        return None

def search_reports_by_content(search_term: str) -> List[Dict[str, Any]]:
    """Search for reports based on their content"""
    # First try using Supabase with RPC function if available
    try:
        if is_db_ready():
            # Try using RPC function if it exists
            try:
                response = supabase.rpc("search_reports", {"search_term": search_term}).execute()
                
                if response.data:
                    logger.info(f"Reports found matching term: {search_term} via Supabase RPC")
                    return response.data
            except Exception:
                # If RPC fails, try direct query
                response = supabase.table(pg_table).select("*").filter("all_data", "ilike", f"%{search_term}%").execute()
                
                if response.data:
                    logger.info(f"Reports found matching term: {search_term} via Supabase filter")
                    return response.data
    except Exception as e:
        logger.warning(f"Error searching reports via Supabase: {str(e)}. Trying direct PostgreSQL connection...")
    
    # Fall back to direct PostgreSQL connection
    try:
        conn = get_postgres_connection()
        if conn is None:
            logger.error("Could not establish PostgreSQL connection")
            return []
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # SQL query to search for reports
        query = f"""
        SELECT * FROM {pg_schema}.{pg_table}
        WHERE all_data ILIKE %s
        ORDER BY created_at DESC;
        """
        
        # Execute the query
        cursor.execute(query, (f"%{search_term}%",))
        
        # Get the results
        results = cursor.fetchall()
        cursor.close()
        
        if results:
            logger.info(f"Reports found matching term: {search_term} via PostgreSQL")
            return [dict(row) for row in results]
        else:
            logger.info(f"No reports found matching term: {search_term} in PostgreSQL")
            return []
            
    except Exception as e:
        logger.error(f"Error searching reports in PostgreSQL database: {str(e)}")
        return []

async def search_missing_people(search_term: str) -> List[Dict[str, Any]]:
    """Search for missing person reports"""
    # First try using Supabase
    try:
        if is_db_ready():
            # Search specifically for missing person reports
            query = supabase.table(pg_table) \
                .select("*") \
                .eq("report_type", "Missing Person (Earthquake)") \
                .filter("all_data", "ilike", f"%{search_term}%") \
                .order("created_at", desc=True)
                
            response = query.execute()
            
            if response.data:
                logger.info(f"Missing person reports found matching term: {search_term} via Supabase")
                return response.data
    except Exception as e:
        logger.warning(f"Error searching missing people via Supabase: {str(e)}. Trying direct PostgreSQL connection...")
    
    # Fall back to direct PostgreSQL connection
    try:
        conn = get_postgres_connection()
        if conn is None:
            logger.error("Could not establish PostgreSQL connection")
            return []
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # SQL query to search for missing person reports
        query = f"""
        SELECT * FROM {pg_schema}.{pg_table}
        WHERE report_type = 'Missing Person (Earthquake)'
        AND all_data ILIKE %s
        ORDER BY created_at DESC;
        """
        
        # Execute the query
        cursor.execute(query, (f"%{search_term}%",))
        
        # Get the results
        results = cursor.fetchall()
        cursor.close()
        
        if results:
            logger.info(f"Missing person reports found matching term: {search_term} via PostgreSQL")
            return [dict(row) for row in results]
        else:
            logger.info(f"No missing person reports found matching term: {search_term} in PostgreSQL")
            return []
            
    except Exception as e:
        logger.error(f"Error searching missing people in PostgreSQL database: {str(e)}")
        return []

async def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    """Async wrapper around get_report_by_id for use in async functions"""
    try:
        # Try using Supabase
        if is_db_ready():
            response = supabase.table(pg_table).select('*').eq('report_id', report_id).execute()
            
            if response and hasattr(response, 'data') and len(response.data) > 0:
                logger.info(f"Report found with ID: {report_id} via Supabase")
                return response.data[0]
        
        # Fall back to direct PostgreSQL connection
        conn = get_postgres_connection()
        if conn is None:
            logger.error("Could not establish PostgreSQL connection")
            return None
            
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # SQL query to get the report
        query = f"""
        SELECT * FROM {pg_schema}.{pg_table}
        WHERE report_id = %s;
        """
        
        # Execute the query
        cursor.execute(query, (report_id,))
        
        # Get the result
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            logger.info(f"Report found with ID: {report_id} via PostgreSQL")
            return dict(result)
        
        # If no results from database, check in-memory storage
        if REPORTS and report_id in REPORTS:
            logger.info(f"Report found with ID: {report_id} in memory storage")
            return REPORTS[report_id]
            
        logger.info(f"No report found with ID: {report_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting report by ID: {str(e)}")
        return None

# Clean up database connections when program exits
def close_connections():
    """Close all database connections"""
    global pg_conn
    
    if pg_conn is not None:
        try:
            pg_conn.close()
            logger.info("PostgreSQL connection closed")
        except Exception as e:
            logger.error(f"Error closing PostgreSQL connection: {str(e)}")
        finally:
            pg_conn = None
