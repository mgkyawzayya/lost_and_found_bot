from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

# Define conversation states
CONTACT_INFO = 0

# ...existing code...

async def contact_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Your contact report logic here
    await update.message.reply_text("Please provide your contact information.")
    return CONTACT_INFO  # Return the next state, not None
    
async def receive_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_info = update.message.text
    context.user_data['contact_info'] = contact_info
    await update.message.reply_text("Thank you for providing your contact information. Your report has been submitted.")
    return ConversationHandler.END  # Make sure to return END, not None

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END  # Add this return statement to fix the error

# ...existing code...

contact_handler = ConversationHandler(
    entry_points=[CommandHandler('contact', contact_report)],
    states={
        CONTACT_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_contact_info)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

# ...existing code...
