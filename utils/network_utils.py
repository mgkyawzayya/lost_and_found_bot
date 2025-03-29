import logging
import time
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger(__name__)

def retry_on_network_error(max_retries: int = 3, backoff_factor: float = 0.5, 
                          allowed_exceptions: tuple = (Exception,)) -> Callable:
    """
    Decorator to retry functions on network errors with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Exponential backoff multiplier
        allowed_exceptions: Tuple of exceptions that should trigger a retry
    
    Returns:
        The decorated function with retry capability
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retry_count = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except allowed_exceptions as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(f"Maximum retries ({max_retries}) exceeded for {func.__name__}: {e}")
                        raise
                    
                    # Calculate exponential backoff time
                    wait_time = backoff_factor * (2 ** (retry_count - 1))
                    logger.warning(f"Attempt {retry_count} failed for {func.__name__}: {e}. "
                                  f"Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
        return wrapper
    return decorator

def is_network_available() -> bool:
    """
    Check if network connection is available.
    
    Returns:
        bool: True if network is available, False otherwise
    """
    import socket
    try:
        # Try to connect to a reliable service (Google DNS)
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except (socket.timeout, socket.error):
        return False

def log_network_status() -> None:
    """Log the current network status"""
    network_available = is_network_available()
    if network_available:
        logger.info("Network connection is available")
    else:
        logger.warning("Network connection is unavailable")
    return network_available
