import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, 
    Filters, ConversationHandler, CallbackContext
)

from config.constants import BOT_TOKEN
from config.states import (
    CHOOSING_REPORT_TYPE, COLLECTING_DATA, 
    PHOTO, DESCRIPTION, SEARCHING_REPORT
)
from handlers.report_handlers import (
    choose_report_type, collect_data, photo, 
    handle_skip_photo, search_report, finalize_report
)
from utils.db_utils import init_db

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start(update: Update, context: CallbackContext) -> int:
    """Start the conversation and ask user what they want to do."""
    reply_keyboard = [
        ['Report Lost Person'], 
        ['Report Found Person'],
        ['Search Reports by ID'],
        ['Contact Report Submitter']
    ]
    
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    
    update.message.reply_text(
        "🙏 Welcome to the Lost and Found Bot! I'm here to help you report lost or found persons "
        "during emergencies.\n\n"
        "အရေးပေါ်အခြေအနေတွင် ပျောက်ဆုံး/တွေ့ရှိသူများကို အစီရင်ခံရန် ကူညီပေးမည်ဖြစ်ပါသည်။\n\n"
        "Please select an option:",
        reply_markup=markup
    )
    
    return CHOOSING_REPORT_TYPE

def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the conversation."""
    update.message.reply_text(
        "Operation cancelled. You can start a new report by typing /start"
    )
    return ConversationHandler.END

def main():
    """Run the bot."""
    # Initialize database
    init_db()
    
    # Create the Updater and pass it your bot's token
    updater = Updater(BOT_TOKEN)
    
    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    
    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_REPORT_TYPE: [
                MessageHandler(Filters.text & ~Filters.command, choose_report_type)
            ],
            COLLECTING_DATA: [
                MessageHandler(Filters.text & ~Filters.command, collect_data)
            ],
            PHOTO: [
                MessageHandler(Filters.photo, photo),
                MessageHandler(Filters.text & ~Filters.command, handle_skip_photo)
            ],
            SEARCHING_REPORT: [
                MessageHandler(Filters.text & ~Filters.command, search_report)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    dispatcher.add_handler(conv_handler)
    
    # Start the Bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
