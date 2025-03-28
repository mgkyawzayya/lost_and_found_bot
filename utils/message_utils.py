import re
import logging
import pytz
from telegram.ext import ApplicationBuilder

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """
    Helper function to escape special characters for Markdown V2 format
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def handle_report_error(update, error):
    """Handle and log errors during report processing."""
    logger.error(f"Error broadcasting message: {error}")
    error_message = escape_markdown_v2(
        "❌ Sorry, there was an error broadcasting your message.\n\n"
        "❌ သင့်အစီရင်ခံစာထုတ်လွှင့်ရာတွင် အမှားအယွင်းများရှိပါသည်။"
    )
    update.message.reply_text(error_message, parse_mode='MarkdownV2')

def create_application(token: str):
    """
    Create a properly configured Application instance with pytz timezone.
    
    Args:
        token: The Telegram bot token
        
    Returns:
        The configured Application instance
    """
    # Configure with UTC timezone from pytz to avoid the APScheduler error
    return ApplicationBuilder().token(token).job_queue_data({"timezone": pytz.UTC}).build()

# Note: For python-telegram-bot v13+, use:
# Updater(token=TOKEN, use_context=True)
# For python-telegram-bot v20+, use:
# Application.builder().token(TOKEN).build()
