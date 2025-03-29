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
import socket
import time

# Import configurations
from config.constants import BOT_TOKEN, VOLUNTEER_TEAMS, SUPABASE_URL, SUPABASE_KEY
from config.states import (
    CHOOSING_REPORT_TYPE, COLLECTING_DATA, PHOTO,
    SEARCHING_REPORT, SEND_MESSAGE, DESCRIPTION,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER,
    CHOOSING_LOCATION, SELECT_URGENCY  # Add the new state
)
from config.supabase_config import get_supabase_client
from utils.db_utils import close_connections

# Import handlers - MODIFIED: removed error_handler from this import
from handlers.report_handlers import (
    choose_report_type, collect_data, finalize_report,
    photo, search_report, send_message_to_submitter, handle_skip_photo,
    search_missing_person, choose_report_to_contact, choose_location,
    select_urgency  # Add this import
)
# Import contact handler
from handlers.contact_handler import contact_handler

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Supabase client with improved error handling
def initialize_supabase_with_retry(max_retries=3, retry_delay=5):
    """Initialize Supabase client with retry logic"""
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            # Try DNS resolution first to provide better error messages
            try:
                # Extract hostname from Supabase URL
                from urllib.parse import urlparse
                parsed_url = urlparse(SUPABASE_URL)
                hostname = parsed_url.hostname
                
                # Test DNS resolution
                socket.gethostbyname(hostname)
                logger.info(f"DNS resolution successful for {hostname}")
            except socket.gaierror as dns_err:
                logger.warning(f"DNS resolution failed: {dns_err}")
                # Continue anyway, as the client might have its own resolution mechanism

            # Attempt to initialize the client
            client = get_supabase_client()
            
            # Test the connection with a simple query
            # Use a more reliable health check that doesn't depend on a specific table
            connection_verified = False
            try:
                # Try a simple system function that should always exist
                health_result = client.rpc('version').execute()
                logger.info("Supabase connection test successful via PostgreSQL version()")
                connection_verified = True
            except Exception as func_err:
                logger.warning(f"PostgreSQL system function check failed: {func_err}")
                
                # Try another approach - use raw SQL if available
                try:
                    # Some Supabase clients support this
                    sql_result = client.sql("SELECT 1 AS connection_test").execute()
                    logger.info("Supabase connection test successful via direct SQL")
                    connection_verified = True
                except Exception as sql_err:
                    logger.warning(f"Direct SQL check failed: {sql_err}")
            
            # If previous checks failed, try actual application tables
            if not connection_verified:
                try:
                    # Try each table that might exist in the application
                    app_tables = ["reports", "users", "missing_persons", "found_items", "lost_items"]
                    for table in app_tables:
                        try:
                            result = client.table(table).select("*").limit(1).execute()
                            logger.info(f"Supabase connection verified via {table} table")
                            connection_verified = True
                            break
                        except Exception as table_err:
                            logger.debug(f"Table check failed for {table}: {table_err}")
                            continue
                except Exception as tables_err:
                    logger.warning(f"All application table checks failed: {tables_err}")
            
            if not connection_verified:
                logger.warning("Unable to verify Supabase connection, but returning client anyway")
                
            return client
            
        except Exception as e:
            last_error = e
            retry_count += 1
            logger.error(f"Supabase initialization attempt {retry_count}/{max_retries} failed: {e}")
            
            if retry_count < max_retries:
                wait_time = retry_delay * retry_count
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
    
    # If we get here, all retries failed
    logger.error(f"Failed to initialize Supabase after {max_retries} attempts. Last error: {last_error}")
    # Return a basic client that will fail gracefully
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize Supabase client with error handling
try:
    supabase = initialize_supabase_with_retry()
    logger.info("Supabase client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    # Still create the variable to avoid None checks throughout the code
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
    """Start the conversation and display a persistent menu."""
    # Set a flag to indicate we're in a conversation
    context.user_data['in_conversation'] = True
    
    # Check if Supabase appears to be working
    connection_warning = ""
    try:
        # Try to use a table we know exists instead of health_check
        test = supabase.table("reports").select("*").limit(1).execute()
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        connection_warning = "⚠️ Database connectivity issues detected. Some features may be limited. ⚠️\n\n" \
                            "ချိတ်ဆက်မှုပြဿနာအချို့ရှိနေပါသည်။ လုပ်ဆောင်ချက်အချို့ ကန့်သတ်ထားနိုင်ပါသည်။"
    
    # Create a persistent keyboard with main menu options
    keyboard = [
        ['Missing Person (Earthquake)', 'Found Person (Earthquake)'],
        ['Request Rescue', 'Offer Help'],
        ['Search Reports by ID', 'Contact Report Submitter'],
        ['Search for Missing Person']  # New option
    ]
    
    # Set one_time_keyboard=False to make the keyboard persistent
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=False,  # Changed to False to make it persistent
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🚨 EARTHQUAKE EMERGENCY RESPONSE 🚨\n\n"
        "I'll help you broadcast critical information during this disaster.\n\n"
        "မြန်မာဘာသာဖြင့် - ငလျင်အန္တရာယ်အတွက် အရေးပေါ် တုံ့ပြန်မှု\n\n"
        "အရေးပေါ် လူပျောက်/တွေ့ရှိမှုများအတွက် ဤ Bot ကို အသုံးပြုနိုင်ပါသည်။\n"
        "ဤဘေးအန္တရာယ်ကာလအတွင်း သတင်းအချက်အလက်များကို ထုတ်ပြန်နိုင်ရန် ကျွန်ုပ်တို့ကူညီပေးမည်။" 
        f"\n\n{connection_warning}\n\n"
        "အစီရင်ခံလိုသည့်အကြောင်းအရာကို အောက်တွင်ရွေးချယ်ပါ:",
        reply_markup=reply_markup
    )
    
    logger.info("User started the bot with persistent menu active.")
    logger.info(f"Returning state CHOOSING_REPORT_TYPE: {CHOOSING_REPORT_TYPE}")
    
    return CHOOSING_REPORT_TYPE

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


async def restore_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restore the main menu after completing an operation."""
    keyboard = [
        ['Missing Person (Earthquake)', 'Found Person (Earthquake)'],
        ['Request Rescue', 'Offer Help'],
        ['Search Reports by ID', 'Contact Report Submitter'],
        ['Search for Missing Person']
    ]
    
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=False,  # Persistent menu
        resize_keyboard=True
    )

    await update.message.reply_text(
        "What would you like to do next?\n\n"
        "ဆက်လက်၍ မည်သည့်လုပ်ဆောင်ချက်ကို လုပ်ဆောင်လိုပါသလဲ?",
        reply_markup=reply_markup
    )
    
    return CHOOSING_REPORT_TYPE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current operation and return to main menu."""
    # Clear specific operation data but keep the conversation active
    for key in list(context.user_data.keys()):
        if key != 'in_conversation':
            context.user_data.pop(key)
    
    # Return to main menu
    return await restore_main_menu(update, context)

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
        "*Main Menu / Main Menu*\n\n"
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

# Modify the error handler to include more specific database error information
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors that occur during the processing of updates."""
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Log the stack trace
    import traceback
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)
    
    # Check if it's a database connection error
    error_message = "Sorry, something went wrong. Please try again or contact support."
    if hasattr(context.error, '__cause__') and context.error.__cause__ is not None:
        if "could not translate host name" in str(context.error.__cause__) or \
           "connection" in str(context.error.__cause__).lower():
            error_message = "We're experiencing database connection issues. Some features may be unavailable. " \
                            "Please try again later or use basic reporting features only."
    
    # Notify user if possible
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"{error_message}\n\n"
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
            SELECT_URGENCY: [  # Add the SELECT_URGENCY state handler
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_urgency)
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_report_to_contact),
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('menu', restore_main_menu)  # Add this to make /menu restore the keyboard
        ]
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
    application.add_handler(CommandHandler('menu', restore_main_menu))
    application.add_handler(CommandHandler('volunteer', volunteer_info))
    application.add_handler(CommandHandler('getid', get_id))
    
    # Handle media - also AFTER the conversation handler
    application.add_handler(MessageHandler(
        filters.PHOTO & ~filters.COMMAND,
        handle_media
    ), group=999)  # Use a high group number to ensure this only runs if no other handler caught the message
    
    # Define an async function for unhandled messages
    async def handle_unhandled_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log unhandled messages."""
        # Check if we're in an active conversation by looking at current conversation state
        # Skip this handler completely if the user data indicates an active conversation
        if context.user_data and ('in_conversation' in context.user_data or 
                                 'report_type' in context.user_data or 
                                 'form_data' in context.user_data or
                                 'all_data' in context.user_data):
            # Skip handling as the conversation handler should handle it
            logger.info("Message appears to be part of a conversation - skipping fallback handler")
            return
            
        text = update.message.text if update.message and hasattr(update.message, 'text') else "Non-text message"
        logger.info(f"Unhandled message: {text}")
        
        # Check if this looks like a command attempt - be helpful
        if text.startswith('/'):
            await update.message.reply_text(
                f"Unrecognized command '{text}'. Try /start, /help, or /menu for available options.\n\n"
                f"အသိအမှတ်မပြုသော command '{text}'။ /start, /help, သို့မဟုတ် /menu ကိုသုံးကြည့်ပါ။"
            )
            return
        
        # Optionally inform the user
        await update.message.reply_text(
            "I'm not sure how to respond to that. Please use /start to access the main menu or /help for assistance.\n\n"
            "ကျွန်ုပ်မည်သို့တုံ့ပြန်ရမည်မသိပါ။ အဓိကစာမျက်နှာကို ဝင်ရောက်ရန် /start သို့မဟုတ် အကူအညီရယူရန် /help ကိုအသုံးပြုပါ။"
        )

    # Fallback handler for any message not caught by other handlers
    # Make it more specific and give it a more restrictive group number
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_unhandled_message,
    ), group=9999)  # Use an even higher group number to ensure this only runs as absolute last resort
    
    # Add error handler - Make sure we're using our defined error handler
    application.add_error_handler(error_handler)
    
    # Option 1: Using atexit module
    import atexit
    from utils.db_utils import close_connections
    atexit.register(close_connections)
    
    # Option 2: or add this to the end of your main function
    try:
        # Add a database connectivity check that doesn't rely on health_check table
        try:
            # First try using the metadata tables which should always exist
            result = supabase.table("pg_catalog.pg_tables").select("*").limit(1).execute()
            logger.info("Database connection confirmed working via catalog query")
        except Exception as catalog_err:
            logger.warning(f"Catalog query failed: {catalog_err}")
            # Try a second method in case the first one fails
            try:
                result = supabase.rpc('get_service_status').execute()
                logger.info("Database connection confirmed working via RPC")
            except Exception as rpc_err:
                logger.warning(f"RPC health check failed: {rpc_err}")
                # Last fallback - try one of the actual application tables
                try:
                    # Use table names we know exist in the database
                    tables = ["reports", "users", "missing_persons", "found_items"]
                    for table in tables:
                        try:
                            result = supabase.table(table).select("*").limit(1).execute()
                            logger.info(f"Database connection confirmed working via {table} table")
                            break
                        except Exception:
                            continue
                except Exception as table_err:
                    logger.warning(f"All table checks failed: {table_err}")
                    raise
    except Exception as e:
        logger.warning(f"All database connection checks failed: {e}")
        logger.info("Bot will run in limited functionality mode")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Critical error starting bot: {e}")
    finally:
        close_connections()

if __name__ == '__main__':
    main()
