import logging
import signal
import sys
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import pytz
from supabase import create_client

# Import configurations
from config.constants import BOT_TOKEN, VOLUNTEER_TEAMS, SUPABASE_URL, SUPABASE_KEY
from config.states import (
    CHOOSING_REPORT_TYPE, COLLECTING_DATA, PHOTO,
    SEARCHING_REPORT, SEND_MESSAGE, DESCRIPTION,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER,
    CHOOSING_LOCATION  # Add the new state
)
from config.supabase_config import get_supabase_client
from utils.db_utils import close_connections

# Import handlers - MODIFIED: removed error_handler from this import
from handlers.report_handlers import (
    choose_report_type, collect_data, finalize_report,
    photo, search_report, send_message_to_submitter, handle_skip_photo,
    search_missing_person, choose_report_to_contact, choose_location
)
# Import contact handler
from handlers.contact_handler import contact_handler

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Supabase client with error handling
try:
    supabase = get_supabase_client()
    logger.info("Supabase client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    # Still create the variable to avoid None checks throughout the code
    # The actual connections will fail, but the application can still start
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Set up signal handlers for graceful shutdown
def signal_handler(sig, frame):
    """Handle shutdown signals by cleaning up resources"""
    signal_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else f"Signal {sig}"
    logger.info(f"{signal_name} received. Cleaning up resources...")
    close_connections()
    sys.exit(0)

# Register signal handlers for various termination scenarios
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
# Add more signal handlers for comprehensive coverage
if hasattr(signal, 'SIGHUP'):
    signal.signal(signal.SIGHUP, signal_handler)  # Terminal closed
if hasattr(signal, 'SIGQUIT'):
    signal.signal(signal.SIGQUIT, signal_handler)  # Quit signal

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask for item type."""
    # Set a flag to indicate we're in a conversation
    context.user_data['in_conversation'] = True
    
    keyboard = [
        ['Missing Person (Earthquake)', 'Found Person (Earthquake)'],
        ['Lost Item', 'Found Item'],
        ['Request Rescue', 'Offer Help'],
        ['Search Reports by ID', 'Contact Report Submitter'],
        ['Search for Missing Person']  # New option
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "🚨 *EARTHQUAKE EMERGENCY RESPONSE* 🚨\n\n"
        "Welcome to the Emergency Lost and Found Bot. "
        "I'll help you broadcast critical information during this disaster.\n\n"
        "မြန်မာဘာသာဖြင့် - ငလျင်အန္တရာယ်အတွက် အရေးပေါ် တုံ့ပြန်မှု\n\n"
        "အရေးပေါ် လူပျောက်/တွေ့ရှိမှုများအတွက် ဤ Bot ကို အသုံးပြုနိုင်ပါသည်။\n"
        "ဤဘေးအန္တရာယ်ကာလအတွင်း သတင်းအချက်အလက်များကို ထုတ်ပြန်နိုင်ရန် ကျွန်ုပ်တို့ကူညီပေးမည်။\n\n"
        "အစီရင်ခံလိုသည့်အကြောင်းအရာကို အောက်တွင်ရွေးချယ်ပါ:",
        reply_markup=reply_markup,
        parse_mode='MARKDOWN'
    )
    
    logger.info("User started the bot. Waiting for menu selection.")
    logger.info(f"Returning state CHOOSING_REPORT_TYPE: {CHOOSING_REPORT_TYPE}")
    
    return CHOOSING_REPORT_TYPE  # Ensure the bot transitions to the correct state

# Add a new function to handle the initial search request
async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the selection from the main menu."""
    text = update.message.text
    
    if text == 'Search Reports by ID':
        await update.message.reply_text(
            "Please enter the Report ID you want to search for:\n\n"
            "ရှာဖွေလိုသည့် အစီရင်ခံစာ ID ကို ရိုက်ထည့်ပါ:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SEARCHING_REPORT
    
    elif text == 'Contact Report Submitter':
        await update.message.reply_text(
            "Please enter the Report ID of the report whose submitter you want to contact:\n\n"
            "ဆက်သွယ်လိုသည့် အစီရင်ခံစာ၏ ID ကို ရိုက်ထည့်ပါ:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SEND_MESSAGE
    
    elif text == 'Search for Missing Person':
        await update.message.reply_text(
            "Please enter a name or details to search for missing persons:\n\n"
            "ပျောက်ဆုံးနေသူများကို ရှာရန် အမည် သို့မဟုတ် အသေးစိတ်အချက်အလက်များ ရိုက်ထည့်ပါ:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SEARCH_MISSING_PERSON
    
    else:
        # Handle normal report types
        return await choose_report_type(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text(
        "Operation cancelled. Use /start to begin again.\n\n"
        "လှုပ်ရှားမှုကို ပယ်ဖျက်လိုက်ပါပြီ။ ထပ်မံစတင်လိုလျှင် /start ကိုသုံးပါ။"
    )
    # Clear the conversation flag
    context.user_data['in_conversation'] = False
    context.user_data.clear()
    return ConversationHandler.END

# Add a new global cancel handler
async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel command that works outside of conversations."""
    await update.message.reply_text(
        "No active operation to cancel. Use /start to begin.\n\n"
        "ပယ်ဖျက်ရန် လှုပ်ရှားမှုမရှိပါ။ စတင်ရန် /start ကိုသုံးပါ။"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help information."""
    await update.message.reply_text(
        "🆘 *EARTHQUAKE EMERGENCY HELP* 🆘\n\n"
        "• Use /start to report missing or found people/items\n"
        "• Be precise with location details\n"
        "• Include contact information\n"
        "• Each report gets a unique ID - save it!\n"
        "• Use 'Search Reports by ID' to find specific reports\n"
        "• Use 'Contact Report Submitter' to message the person who posted\n"
        "• Use 'Search for Missing Person' to find people by name or details\n\n"
        "🆘 *ငလျင်အရေးပေါ်အကူအညီ* 🆘\n\n"
        "• ပျောက်ဆုံးသို့မဟုတ်တွေ့ရှိသူများ၊ သတင်းအချက်အလက်တင်ရန် /start ကိုသုံးပါ\n"
        "• တည်နေရာအသေးစိတ်ကို တိကျစွာဖော်ပြပါ\n"
        "• ဆက်သွယ်ရန်အချက်အလက်ထည့်သွင်းပါ\n"
        "• အစီရင်ခံစာတိုင်းတွင် သီးသန့်အမှတ်စဉ်ရှိပါသည် - သိမ်းထားပါ!\n"
        "• For volunteer contacts, type /volunteer\n"
        "• If you want a list of all commands, type /menu\n\n"
        "Stay safe and avoid damaged structures!",
        parse_mode='MARKDOWN'
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands."""
    await update.message.reply_text(
        "*Main Menu / မန်ယူ*\n\n"
        "/start - Begin reporting a missing/found person or item\n"
        "/start search - Search for a report by ID\n"
        "/volunteer - View volunteer contact information\n"
        "/help - General help and emergency numbers\n"
        "/cancel - Cancel current operation\n"
        "/menu - Show this menu\n"
        "/getid - Get your User ID and username",
        parse_mode='MARKDOWN'
    )

async def volunteer_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show volunteer team information."""
    message_lines = ["*Available Volunteer Teams:*"]
    for team in VOLUNTEER_TEAMS:
        message_lines.append(
            f"• *{team['name']}*\n"
            f"  Phone: {team['phone']}\n"
            f"  Info: {team['info']}\n"
        )
    await update.message.reply_text("\n".join(message_lines), parse_mode='MARKDOWN')

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user ID information."""
    user = update.effective_user
    await update.message.reply_text(
        f"Your User ID: `{user.id}`\n"
        f"Your Name: {user.first_name}\n"
        f"Your Username: @{user.username}",
        parse_mode='MARKDOWN'
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle media messages outside conversation."""
    await update.message.reply_text(
        "Please use /start to submit a structured emergency report.\n\n"
        "ဤဖိုင်တစ်ခုတည်းမတင်သင့်ပါ၊ တည်ချက်ပြည့်စုံရန် /start ကို အသုံးပြုပါ။"
    )

# Define the error handler locally to avoid conflicts
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors that occur during the processing of updates."""
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Log the stack trace
    import traceback
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)
    
    # Notify user if possible
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Sorry, something went wrong. Please try again or contact support.\n\n"
                "တစ်စုံတစ်ခု မှားယွင်းသွားပါသည်။ ထပ်ကြိုးစားပါ သို့မဟုတ် အကူအညီရယူပါ။"
            )
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

def main():
    """Start the bot."""
    # Create the Application directly with the token and defaults
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_REPORT_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_action)
            ],
            CHOOSING_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_location)
            ],
            COLLECTING_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_data)
            ],
            PHOTO: [
                # Make sure photo handler gets priority over text handler
                MessageHandler(filters.PHOTO, photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_skip_photo)
            ],
            SEARCHING_REPORT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_report)
            ],
            SEND_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_message_to_submitter)
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_message_to_submitter)
            ],
            SEARCH_MISSING_PERSON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_missing_person)
            ],
            SEND_MESSAGE_TO_REPORTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_report_to_contact)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Add detailed debug logging - this is important!
    logger.info("ConversationHandler created with the following states:")
    for state, handlers in conv_handler.states.items():
        logger.info(f"State {state}: {handlers}")
        
    # IMPORTANT: log the PHOTO state handlers specifically to debug
    if PHOTO in conv_handler.states:
        logger.info(f"PHOTO state handlers: {conv_handler.states[PHOTO]}")

    # IMPORTANT: Add the conversation handler FIRST
    application.add_handler(conv_handler)
    
    # Add the contact handler
    application.add_handler(contact_handler)
    
    # Add a global cancel command handler that works outside of conversations
    application.add_handler(CommandHandler('cancel', global_cancel))

    # Add these AFTER the conversation handler
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('menu', menu_command))
    application.add_handler(CommandHandler('volunteer', volunteer_info))
    application.add_handler(CommandHandler('getid', get_id))
    
    # Handle media - also AFTER the conversation handler
    application.add_handler(MessageHandler(
        filters.PHOTO & ~filters.COMMAND,
        handle_media
    ))
    
    # Define an async function for unhandled messages
    async def handle_unhandled_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log unhandled messages."""
        # Check if we're in an active conversation
        if context.user_data.get('in_conversation'):
            # Skip handling as the conversation handler will handle it
            return
            
        text = update.message.text if update.message and hasattr(update.message, 'text') else "Non-text message"
        logger.info(f"Unhandled message: {text}")
        # Optionally inform the user
        await update.message.reply_text(
            "I'm not sure how to respond to that. Please use /start to access the main menu or /help for assistance.\n\n"
            "ကျွန်ုပ်မည်သို့တုံ့ပြန်ရမည်မသိပါ။ အဓိကစာမျက်နှာကို ဝင်ရောက်ရန် /start သို့မဟုတ် အကူအညီရယူရန် /help ကိုအသုံးပြုပါ။"
        )
    
    # Fallback handler for any message not caught by other handlers
    # Make it more specific by only handling text messages to avoid conflict with the conversation handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_unhandled_message,
    ), group=999)  # Use a high group number to ensure this only runs if no other handler caught the message
    
    # Add error handler - Make sure we're using our defined error handler
    application.add_error_handler(error_handler)
    
    # Option 1: Using atexit module
    import atexit
    from utils.db_utils import close_connections
    atexit.register(close_connections)
    
    # Option 2: or add this to the end of your main function
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        close_connections()

if __name__ == '__main__':
    main()
