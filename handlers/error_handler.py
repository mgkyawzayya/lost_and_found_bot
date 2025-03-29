import logging
from telegram import Update
from telegram.ext import ContextTypes

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Log the error before we do anything else
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Send a message to the user
    if update and update.effective_message:
        error_message = "Sorry, something went wrong. Please try again later."
        await update.effective_message.reply_text(error_message)
    
    # You could also forward the error to a dedicated chat for debugging
    # await context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=f"An error occurred: {context.error}")
