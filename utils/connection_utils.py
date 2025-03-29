import logging
import socket
from functools import wraps
import time
from typing import Callable, Any, Dict

logger = logging.getLogger(__name__)

def with_connection_retry(max_retries=3, delay_seconds=2, backoff_factor=2):
    """
    Decorator to retry database operations with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        delay_seconds: Initial delay between retries in seconds
        backoff_factor: Multiplier for delay between retries
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = delay_seconds
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    logger.warning(f"Database operation failed (attempt {attempt+1}/{max_retries}): {e}")
                    
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                        delay *= backoff_factor
            
            # If we get here, all retries failed
            logger.error(f"Database operation failed after {max_retries} attempts. Last error: {last_exception}")
            raise last_exception
        
        return wrapper
    return decorator

def check_dns_resolution(hostname: str) -> Dict[str, Any]:
    """
    Check if DNS resolution for a hostname is working
    
    Args:
        hostname: Hostname to check
        
    Returns:
        Dictionary with status and details
    """
    try:
        ip_address = socket.gethostbyname(hostname)
        return {
            "success": True,
            "hostname": hostname,
            "ip_address": ip_address,
            "message": f"Successfully resolved {hostname} to {ip_address}"
        }
    except socket.gaierror as e:
        return {
            "success": False,
            "hostname": hostname,
            "error": str(e),
            "message": f"DNS resolution failed for {hostname}: {e}"
        }

def fallback_operation(fallback_result=None, log_error=True):
    """
    Decorator to provide fallback for database operations
    
    Args:
        fallback_result: Value to return if operation fails
        log_error: Whether to log the error
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    logger.error(f"Operation {func.__name__} failed: {e}")
                return fallback_result
        
        return wrapper
    return decorator
