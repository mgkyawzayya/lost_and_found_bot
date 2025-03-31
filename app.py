import logging
import signal
import sys
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand, BotCommandScopeDefault, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import pytz
from supabase import create_client
import socket
import time
import asyncio


# Import configurations
from config.constants import BOT_TOKEN, VOLUNTEER_TEAMS, SUPABASE_URL, SUPABASE_KEY
from config.states import (
    CHOOSING_REPORT_TYPE, COLLECTING_DATA, PHOTO,
    SEARCHING_REPORT, SEND_MESSAGE, DESCRIPTION,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER,
    CHOOSING_LOCATION, SELECT_URGENCY, UPDATE_REPORT_STATUS, CHOOSE_STATUS,
    COLLECT_NAME, COLLECT_AGE, COLLECT_GENDER, COLLECT_DESCRIPTION, 
    COLLECT_LAST_SEEN_LOCATION, COLLECT_LAST_SEEN_TIME, COLLECT_MEDICAL_INFO,
    COLLECT_CONTACT_INFO, COLLECT_EXACT_LOCATION, COLLECT_PEOPLE_COUNT,
    COLLECT_INJURIES, COLLECT_BUILDING_CONDITION, COLLECT_RELATIONSHIP, 
    COLLECT_CURRENT_LOCATION, COLLECT_HELP_TYPE, COLLECT_RESOURCES, COLLECT_AVAILABILITY, COLLECT_CUSTOM_COORDINATES
)
from config.supabase_config import get_supabase_client
from utils.db_utils import close_connections, update_existing_reports_status

# Import handlers - MODIFIED: removed error_handler from this import
from handlers.report_handlers import (
    choose_report_type, collect_data, finalize_report,
    photo, search_report, send_message_to_submitter, handle_skip_photo,
    search_missing_person, choose_report_to_contact, choose_location,
    select_urgency, update_report_status, choose_status,
    collect_name, collect_age, collect_gender, collect_description,
    collect_last_seen_location, collect_last_seen_time, collect_medical_info,
    collect_contact_info, collect_exact_location, collect_exact_location_coordinates,
    collect_people_count, collect_injuries, collect_building_condition,
    collect_relationship, collect_current_location,
    collect_help_type, collect_resources, collect_availability,
    collect_custom_coordinates

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
    """Start the conversation and show main menu."""
    user = update.effective_user
    await update.message.reply_text(
        f"မင်္ဂလာပါ {user.first_name}! \n\n"
        f"ငလျင်ဘေးအတွက် ကူညီဖော်ရွေဆက်သွယ်ရေး စနစ်သို့ ကြိုဆိုပါသည်။\n\n"
        f"ကျေးဇူးပြု၍ ဆောင်ရွက်လိုသည့် လုပ်ငန်းကို ရွေးချယ်ပါ:"
    )
    
    # Show menu
    await show_main_menu(update, context)
    
    return CHOOSING_REPORT_TYPE

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the main menu keyboard."""
    keyboard = [
        ['လူပျောက်တိုင်မယ်', 'သတင်းပို့မယ်'],
        ['အကူအညီတောင်းမယ်', 'အကူအညီပေးမယ်'],
        ['ID နဲ့ လူရှာမယ်', 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်'],
        ['နာမည်နဲ့ လူပျောက်ရှာမယ်', 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်']
    ]
    
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=False,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "ဆက်လက်၍ မည်သည့်လုပ်ဆောင်ချက်ကို လုပ်ဆောင်လိုပါသလဲ?",
        reply_markup=reply_markup
    )

# Add a new function to handle the initial search request
async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the selection from the main menu."""
    text = update.message.text
    
    if text == 'ID နဲ့ လူရှာမယ်':
        await update.message.reply_text(
            "ရှာဖွေလိုသည့် အစီရင်ခံစာ ID ကို ရိုက်ထည့်ပါ:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SEARCHING_REPORT
    
    elif text == 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်':
        await update.message.reply_text(
            "ဆက်သွယ်လိုသည့် အစီရင်ခံစာ၏ ID ကို ရိုက်ထည့်ပါ:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SEND_MESSAGE
    
    elif text == 'နာမည်နဲ့ လူပျောက်ရှာမယ်':
        await update.message.reply_text(
            "ပျောက်ဆုံးနေသူများကို ရှာရန် အမည် သို့မဟုတ် အသေးစိတ်အချက်အလက်များ ရိုက်ထည့်ပါ:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SEARCH_MISSING_PERSON
    
    # Handle other report types
    elif text == 'လူပျောက်တိုင်မယ်':
        context.user_data['report_type'] = 'Missing Person (Earthquake)'
        await update.message.reply_text(
            "သင်နေထိုင်သည့် မြို့ သို့မဟုတ် ဒေသကို ရွေးချယ်ပါ:",
            reply_markup=ReplyKeyboardMarkup([
                ['ရန်ကုန်', 'မန္တလေး'],
                ['နေပြည်တော်', 'ပဲခူး'],
                ['စစ်ကိုင်း', 'မကွေး'],
                ['ဧရာဝတီ', 'တနင်္သာရီ'],
                ['မွန်', 'ရှမ်း'],
                ['ကချင်', 'ကယား/ကရင်နီ'],
                ['ကရင်', 'ချင်း'],
                ['ရခိုင်', 'အခြား']
            ], resize_keyboard=True)
        )
        return CHOOSING_LOCATION
    
    elif text == 'သတင်းပို့မယ်':
        context.user_data['report_type'] = 'Found Person (Earthquake)'
        await update.message.reply_text(
            "သင်နေထိုင်သည့် မြို့ သို့မဟုတ် ဒေသကို ရွေးချယ်ပါ:",
            reply_markup=ReplyKeyboardMarkup([
                ['ရန်ကုန်', 'မန္တလေး'],
                ['နေပြည်တော်', 'ပဲခူး'],
                ['စစ်ကိုင်း', 'မကွေး'],
                ['ဧရာဝတီ', 'တနင်္သာရီ'],
                ['မွန်', 'ရှမ်း'],
                ['ကချင်', 'ကယား/ကရင်နီ'],
                ['ကရင်', 'ချင်း'],
                ['ရခိုင်', 'အခြား']
            ], resize_keyboard=True)
        )
        return CHOOSING_LOCATION
        
    elif text == 'အကူအညီတောင်းမယ်':
        context.user_data['report_type'] = 'Request Rescue'
        await update.message.reply_text(
            "သင်နေထိုင်သည့် မြို့ သို့မဟုတ် ဒေသကို ရွေးချယ်ပါ:",
            reply_markup=ReplyKeyboardMarkup([
                ['ရန်ကုန်', 'မန္တလေး'],
                ['နေပြည်တော်', 'ပဲခူး'],
                ['စစ်ကိုင်း', 'မကွေး'],
                ['ဧရာဝတီ', 'တနင်္သာရီ'],
                ['မွန်', 'ရှမ်း'],
                ['ကချင်', 'ကယား/ကရင်နီ'],
                ['ကရင်', 'ချင်း'],
                ['ရခိုင်', 'အခြား']
            ], resize_keyboard=True)
        )
        return CHOOSING_LOCATION
        
    elif text == 'အကူအညီပေးမယ်':
        context.user_data['report_type'] = 'Offer Help'
        await update.message.reply_text(
            "သင်နေထိုင်သည့် မြို့ သို့မဟုတ် ဒေသကို ရွေးချယ်ပါ:",
            reply_markup=ReplyKeyboardMarkup([
                ['ရန်ကုန်', 'မန္တလေး'],
                ['နေပြည်တော်', 'ပဲခူး'],
                ['စစ်ကိုင်း', 'မကွေး'],
                ['ဧရာဝတီ', 'တနင်္သာရီ'],
                ['မွန်', 'ရှမ်း'],
                ['ကချင်', 'ကယား/ကရင်နီ'],
                ['ကရင်', 'ချင်း'],
                ['ရခိုင်', 'အခြား']
            ], resize_keyboard=True)
        )
        return CHOOSING_LOCATION

    elif text == 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်':
        await update.message.reply_text(
            "အခြေအနေပြင်ဆင်လိုသည့် အစီရင်ခံစာ ID ကို ရိုက်ထည့်ပါ:\n\n"
            "Please enter the ID of the report you want to update:",
            reply_markup=ReplyKeyboardRemove()
        )
        return UPDATE_REPORT_STATUS
    
    else:
        # Show a helpful message guiding users back to the main menu options
        await update.message.reply_text(
            "❓ I don't understand that command. Please use the keyboard buttons to navigate.\n\n"
            "Command ကို နားမလည်ပါ။ ကျေးဇူးပြု၍ ရွေးချယ်ခွင့်ခလုတ်များကို အသုံးပြုပါ။",
            reply_markup=ReplyKeyboardMarkup([
                ['လူပျောက်တိုင်မယ်', 'သတင်းပို့မယ်'],
                ['အကူအညီတောင်းမယ်', 'အကူအညီပေးမယ်'],
                ['ID နဲ့ လူရှာမယ်', 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်'],
                ['နာမည်နဲ့ လူပျောက်ရှာမယ်', 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်']
            ], resize_keyboard=True)
        )
        return CHOOSING_REPORT_TYPE

async def handle_unexpected_input(update: Update, context: ContextTypes.DEFAULT_TYPE, expected_format: str = None) -> int:
    """
    General handler for unexpected inputs in any state.
    
    Args:
        update: The update object
        context: The context object
        expected_format: Optional formatted string showing expected input format
        
    Returns:
        The same state to allow the user to try again
    """
    message = (
        "❌ Your input doesn't match what's expected at this step.\n"
        "သင့်ရဲ့ ထည့်သွင်းမှုသည် ဒီအဆင့်မှာ မွှော်လင့်ထားတာနဲ့ မကိုက်ညီပါ။\n\n"
    )
    
    if expected_format:
        message += f"Expected format:\n{expected_format}\n\n"
    
    message += (
        "Please try again or use /cancel to start over.\n"
        "ထပ်စမ်းကြည့်ပါ သို့မဟုတ် အစကနေစဖို့ /cancel ကိုသုံးပါ။"
    )
    
    await update.message.reply_text(message)
    
    # Return the current state (passed from the calling handler)
    # This must be implemented correctly in each handler that calls this function
    return context.user_data.get('current_state', CHOOSING_REPORT_TYPE)

async def restore_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restore the main menu after completing an operation."""
    keyboard = [
        ['လူပျောက်တိုင်မယ်', 'သတင်းပို့မယ်'],
        ['အကူအညီတောင်းမယ်', 'အကူအညီပေးမယ်'],
        ['ID နဲ့ လူရှာမယ်', 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်'],
        ['နာမည်နဲ့ လူပျောက်ရှာမယ်', 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်']  # Add new option
    ]
    
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=False,
        resize_keyboard=True
    )

    await update.message.reply_text(
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

async def handle_greeting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle common greetings and direct users to the main menu."""
    text = update.message.text.lower()
    
    common_greetings = [
        "hello", "hi", "hey", "how are you", "test", 
        "ဟယ်လို", "မင်္ဂလာပါ", "နေကောင်းလား"
    ]
    
    if any(greeting in text for greeting in common_greetings):
        await update.message.reply_text(
            "👋 Hello! Welcome to the Lost and Found Bot.\n\n"
            "မင်္ဂလာပါ! ပျောက်ဆုံးရှာဖွေရေး ဘော့တ်သို့ ကြိုဆိုပါတယ်။\n\n"
            "Please use the menu below to get started:"
            "စတင်ရန် အောက်ပါမီနူးကို အသုံးပြုပါ။",
            reply_markup=ReplyKeyboardMarkup([
                ['လူပျောက်တိုင်မယ်', 'သတင်းပို့မယ်'],
                ['အကူအညီတောင်းမယ်', 'အကူအညီပေးမယ်'],
                ['ID နဲ့ လူရှာမယ်', 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်'],
                ['နာမည်နဲ့ လူပျောက်ရှာမယ်', 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်']
            ], resize_keyboard=True)
        )
        return CHOOSING_REPORT_TYPE
    
    # If not a recognized greeting, pass to the normal choose_action handler
    return await choose_action(update, context)

    
# Add a new global cancel handler
async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel command that works outside of conversations."""
    await update.message.reply_text(
        "No active operation to cancel. Use /start to begin.\n\n"
        "ပယ်ဖျက်ရန် လှုပ်ရှားမှုမရှိပါ။ စတင်ရန် /start ကိုသုံးပါ။"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help information in Burmese."""
    await update.message.reply_text(
        "🆘 *ငလျင် အရေးပေါ် အကူအညီ* 🆘\n\n"
        "• လူပျောက်/တွေ့ရှိမှုများအတွက် /start ကိုသုံးပါ\n"
        "• တည်နေရာအသေးစိတ်ကို တိကျစွာဖော်ပြပါ\n"
        "• ဆက်သွယ်ရန်အချက်အလက် ထည့်သွင်းပါ\n"
        "• အစီရင်ခံစာတိုင်းတွင် သီးသန့် ID ရှိသည် - သိမ်းထားပါ!\n"
        "• 'ID နဲ့ လူရှာမယ်' ကို အသုံးပြု၍ အစီရင်ခံစာများကို ရှာပါ\n"
        "• 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်' ကိုသုံး၍ သတင်းပို့သူထံ စာပို့ပါ\n"
        "• 'နာမည်နဲ့ လူပျောက်ရှာမယ်' ကိုသုံး၍ အမည်ဖြင့် ရှာဖွေပါ\n"
        "• 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်' ကိုသုံး၍ အစီရင်ခံစာ၏ အခြေအနေကို ပြင်ဆင်ပါ\n\n"
        "• စေတနာ့ဝန်ထမ်း အဖွဲ့များ ဆက်သွယ်ရန် /volunteer ကိုရိုက်ပါ\n"
        "• ရရှိနိုင်သည့် မီနူးအားလုံးစာရင်းကို ကြည့်ရန် /menu ကိုရိုက်ပါ\n\n"
        "ဘေးကင်းလုံခြုံပါစေ၊ ပျက်စီးနေသော အဆောက်အအုံများကို ရှောင်ကြဉ်ပါ!",
        parse_mode='MARKDOWN'
    )


async def setup_burmese_commands(application: Application):
    """Set up the bot commands menu button with Burmese labels"""
    commands = [
        BotCommand("start", "အဓိက မီနူးများကို ပြရန်"),
        BotCommand("help", "အကူအညီနှင့် လမ်းညွှန်ချက်များ"),
        BotCommand("menu", "မီနူးအားလုံးကို ကြည့်ရန်"),
        BotCommand("volunteer", "စေတနာ့ဝန်ထမ်း ဆက်သွယ်ရန်"),
        BotCommand("cancel", "လက်ရှိလုပ်ဆောင်နေသည်ကို ပယ်ဖျက်ရန်"),
        BotCommand("getid", "သင့် User ID ကို ကြည့်ရန်")
    ]
    
    await application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Bot commands menu set up with Burmese labels")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands in Burmese."""
    await update.message.reply_text(
        "*အဓိက မီနူးများ*\n\n"
        "/start - ပျောက်ဆုံး/တွေ့ရှိသူ အစီရင်ခံရန် စတင်ပါ\n"
        "/volunteer - စေတနာ့ဝန်ထမ်း ဆက်သွယ်ရန် အချက်အလက်\n"
        "/help - အကူအညီနှင့် အရေးပေါ်ဖုန်းနံပါတ်များ\n"
        "/cancel - လက်ရှိ လုပ်ဆောင်နေသော လုပ်ငန်းကို ပယ်ဖျက်ရန်\n"
        "/menu - ဤမီနူးကို ပြရန်\n"
        "/getid - သင့် User ID နှင့် အသုံးပြုသူအမည်ကို ရယူပါ",
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
    username = user.username if user.username else "None"
    
    # Fix the markdown formatting
    await update.message.reply_text(
        f"Your User ID: `{user.id}`\n"
        f"Your Name: {user.first_name}\n"
        f"Your Username: @{username}",
        parse_mode='Markdown'  # Use 'Markdown' instead of 'MARKDOWN'
    )

# Ensure the function is correctly handling the menu option
# Ensure the function is correctly handling the menu option
async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle main menu button selections and route to the appropriate handler."""
    selection = update.message.text.strip()
    
    logger.info(f"Menu selection received: {selection}")
    
    # Map button selections to appropriate actions
    if selection == 'လူပျောက်တိုင်မယ်':
        context.user_data['report_type'] = 'Missing Person (Earthquake)'
        return await choose_report_type(update, context)
        
    elif selection == 'သတင်းပို့မယ်':
        context.user_data['report_type'] = 'Found Person (Earthquake)'
        return await choose_report_type(update, context)
        
    elif selection == 'အကူအညီတောင်းမယ်':
        context.user_data['report_type'] = 'Request Rescue'
        return await choose_report_type(update, context)
        
    elif selection == 'အကူအညီပေးမယ်':
        context.user_data['report_type'] = 'Offer Help'
        return await choose_report_type(update, context)
        
    elif selection == 'ID နဲ့ လူရှာမယ်':
        return await handle_search_by_id(update, context)
        
    elif selection == 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်':
        return await handle_contact_reporter(update, context)
        
    elif selection == 'နာမည်နဲ့ လူပျောက်ရှာမယ်':
        return await handle_search_by_name(update, context)
        
    elif selection == 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်':
        return await handle_update_status(update, context)
        
    else:
        # Default case - treat as report type
        logger.info(f"Unrecognized menu option: {selection}, treating as report_type")
        context.user_data['report_type'] = selection
        return await choose_report_type(update, context)

# Add these helper functions for the menu options
# Helper functions for menu navigation
async def handle_search_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle search by ID request."""
    await update.message.reply_text(
        "အစီရင်ခံစာနံပါတ် (ID) ကို ရိုက်ထည့်ပါ။\n\n"
        "Please enter the report ID:"
    )
    return SEARCHING_REPORT

async def handle_contact_reporter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle contact reporter request."""
    # Clear previous data
    if 'matching_reports' in context.user_data:
        del context.user_data['matching_reports']
    if 'contact_report' in context.user_data:
        del context.user_data['contact_report']
    if 'contact_report_id' in context.user_data:
        del context.user_data['contact_report_id']
    
    await update.message.reply_text(
        "ဆက်သွယ်လိုသည့် အစီရင်ခံစာနံပါတ် (ID) ကို ရိုက်ထည့်ပါ။\n\n"
        "Please enter the report ID of the submitter you want to contact:"
    )
    return SEND_MESSAGE_TO_REPORTER

async def handle_search_by_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle search by name request."""
    await update.message.reply_text(
        "ရှာဖွေလိုသော လူပျောက်၏ အမည် သို့မဟုတ် အခြားအသေးစိတ်ကို ရိုက်ထည့်ပါ။\n\n"
        "Please enter the name or other details of the missing person:"
    )
    return SEARCH_MISSING_PERSON

async def handle_update_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle update status request."""
    await update.message.reply_text(
        "အခြေအနေပြင်ဆင်လိုသည့် အစီရင်ခံစာနံပါတ် (ID) ကို ရိုက်ထည့်ပါ။\n\n"
        "Please enter the report ID you want to update:"
    )
    return UPDATE_REPORT_STATUS

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

    application.post_init = setup_burmese_commands

    
    # Main conversation handler
    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_location)
            ],
            COLLECTING_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_data)
            ],
            # Step-by-step form collection states
            COLLECT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_name)
            ],
            COLLECT_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_age)
            ],
            COLLECT_GENDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_gender)
            ],
            COLLECT_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_description)
            ],
            COLLECT_LAST_SEEN_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_last_seen_location)
            ],
            COLLECT_EXACT_LOCATION: [
                MessageHandler(filters.LOCATION, collect_exact_location_coordinates),
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_exact_location)
            ],
            COLLECT_LAST_SEEN_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_last_seen_time)
            ],
            COLLECT_MEDICAL_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_medical_info)
            ],
            COLLECT_CONTACT_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_contact_info)
            ],
            COLLECT_PEOPLE_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_people_count)
            ],
            COLLECT_INJURIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_injuries)
            ],
            COLLECT_BUILDING_CONDITION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_building_condition)
            ],
            COLLECT_RELATIONSHIP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_relationship)
            ],
            COLLECT_CURRENT_LOCATION: [  # Add this missing state
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_current_location)
            ],
            COLLECT_HELP_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_help_type)
            ],
            COLLECT_RESOURCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_resources)
            ],
            COLLECT_AVAILABILITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_availability)
            ],
            # The rest of your existing states
            SELECT_URGENCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_urgency)
            ],
            PHOTO: [
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
            ],
            UPDATE_REPORT_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, update_report_status)
            ],
            CHOOSE_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_status)
            ],
            COLLECT_HELP_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_help_type)
            ],
            COLLECT_RESOURCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_resources)
            ],
            COLLECT_AVAILABILITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_availability)
            ],
            # In the ConversationHandler states dictionary
            COLLECT_CUSTOM_COORDINATES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_custom_coordinates)
            ],
            CHOOSING_REPORT_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_selection)  # Use handle_menu_selection here
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('menu', restore_main_menu)
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
    asyncio.run(update_existing_reports_status())
