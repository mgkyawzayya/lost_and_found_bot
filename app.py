import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import pytz

# Import configurations
from config.constants import BOT_TOKEN, VOLUNTEER_TEAMS
from config.states import (
    CHOOSING_REPORT_TYPE, COLLECTING_DATA, PHOTO,
    SEARCHING_REPORT, SEND_MESSAGE, DESCRIPTION,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER
)

# Import handlers
from handlers.report_handlers import (
    choose_report_type, collect_data, finalize_report,
    photo, search_report, send_message_to_submitter, handle_skip_photo,
    search_missing_person, choose_report_to_contact
)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask for item type."""
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

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text(
        "Operation cancelled. Use /start to begin again.\n\n"
        "လှုပ်ရှားမှုကို ပယ်ဖျက်လိုက်ပါပြီ။ ထပ်မံစတင်လိုလျှင် /start ကိုသုံးပါ။"
    )
    context.user_data.clear()
    return ConversationHandler.END

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

def main():
    """Start the bot."""
    # Create the Application directly with the token and defaults
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_REPORT_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_report_type)
            ],
            COLLECTING_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_data)
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
            # Add the new states and handlers
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

    # IMPORTANT: Add the conversation handler FIRST
    application.add_handler(conv_handler)
    
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
    
    # Fallback handler for any message not caught by other handlers
    application.add_handler(MessageHandler(
        filters.ALL,
        lambda update, context: logger.info(f"Unhandled message: {update.message.text}")
    ))
    
    # Start the bot
    logger.info("Starting the bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
