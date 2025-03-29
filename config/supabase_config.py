"""
Supabase Configuration

This file contains configuration variables for connecting to Supabase.
Replace the placeholder values with your actual Supabase credentials.
"""
import logging
from supabase import create_client
from config.constants import SUPABASE_URL, SUPABASE_KEY
from utils.network_utils import retry_on_network_error, log_network_status

logger = logging.getLogger(__name__)

# Global client to be reused
_supabase_client = None

@retry_on_network_error(max_retries=3)
def get_supabase_client(force_new=False):
    """
    Get or create a Supabase client with retry capability.
    
    Args:
        force_new (bool): If True, creates a new client even if one already exists
    
    Returns:
        A configured Supabase client
    """
    global _supabase_client
    
    if _supabase_client is None or force_new:
        # Log network status before attempting connection
        network_available = log_network_status()
        if not network_available:
            logger.warning("Creating Supabase client with limited network connectivity")
            
        logger.info(f"Initializing Supabase client with URL: {SUPABASE_URL[:20]}...")
        try:
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            
            # Test the connection by making a simple query
            try:
                # Adjust this to match your actual table name
                _supabase_client.table('reports').select('id').limit(1).execute()
                logger.info("Supabase connection test successful")
            except Exception as e:
                error_msg = str(e).lower()
                if "nodename nor servname provided, or not known" in error_msg or "name resolution" in error_msg:
                    logger.error(f"DNS resolution failed for Supabase host: {e}")
                    logger.info(f"Please check your internet connection and the SUPABASE_URL value")
                elif "connection" in error_msg or "timeout" in error_msg:
                    logger.error(f"Network connectivity issue with Supabase: {e}")
                else:
                    logger.error(f"Supabase connection test failed: {e}")
                # Still return the client, as connection might work later
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            # Create a dummy client that will raise appropriate errors when used
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    return _supabase_client
