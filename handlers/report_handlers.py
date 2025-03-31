from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
import uuid
import logging
import asyncio
from datetime import datetime
import pytz  # Import pytz for timezone handling
import io, re
import boto3
from botocore.client import Config
import os

from utils.message_utils import escape_markdown_v2
from utils.db_utils import save_report, get_report_by_id, search_reports_by_content, search_missing_people, get_report, update_report_status_in_db
from config.constants import PRIORITIES, CHANNEL_ID
from config.states import (
    PHOTO, COLLECTING_DATA, SEARCHING_REPORT, DESCRIPTION, SEND_MESSAGE,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER, CHOOSING_LOCATION, CHOOSING_REPORT_TYPE,
    SELECT_URGENCY, UPDATE_REPORT_STATUS, CHOOSE_STATUS  # Add CHOOSE_STATUS here
)

# Configure logger
logger = logging.getLogger(__name__)

# In-memory storage for reports if database is not available
REPORTS = {}

async def choose_report_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's selection of report type."""
    text = update.message.text
    
    report_type_map = {
        'လူပျောက်တိုင်မယ်': 'Missing Person (Earthquake)',
        'သတင်းပို့မယ်': 'Found Person (Earthquake)',
        'အကူအညီတောင်းမယ်': 'Request Rescue',
        'အကူအညီပေးမယ်': 'Offer Help'
    }
    
    # Use the mapped report type if available, otherwise use the original text
    context.user_data['report_type'] = report_type_map.get(text, text)
    
    # Make sure to set this flag to indicate we're in a conversation
    context.user_data['in_conversation'] = True
    
    # Check if the report is high urgency (trapped/missing)
    high_urgency_types = [
        'Missing Person (Earthquake)', 
        'Request Rescue'
    ]
    
    if text in high_urgency_types:
        # For high urgency reports, first ask for location
        keyboard = [
            ['ရန်ကုန်', 'မန္တလေး', 'နေပြည်တော်'],
            ['ပဲခူး', 'စစ်ကိုင်း', 'မကွေး'],
            ['ဧရာဝတီ', 'တနင်္သာရီ', 'မွန်'],
            ['ရှမ်း', 'ကချင်', 'ကယား'],
            ['ကရင်', 'ချင်း', 'ရခိုင်'],
            ['အခြားတည်နေရာ']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ *HIGH URGENCY ALERT* ⚠️\n\n"
            "Please select your location to help responders find you quickly:\n\n"
            "သင့်တည်နေရာကို ရွေးချယ်ပေးပါ။ ကူညီရှာဖွေသူများအတွက် အရေးကြီးပါသည်။",
            reply_markup=reply_markup,
            parse_mode='MARKDOWN'
        )
        return CHOOSING_LOCATION
        
    else:
        # For normal reports, proceed with regular data collection
        context.user_data['form_data'] = {}
        
        # Get instructions based on report type
        instructions = get_instructions_by_type(text)
        
        # Send instructions to user
        await update.message.reply_text(
            instructions,
            parse_mode='MARKDOWN'
        )
        
        return COLLECTING_DATA

async def choose_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle location selection for high urgency reports."""
    location = update.message.text
    context.user_data['location'] = location
    
    # Set location prefix for case ID
    location_prefixes = {
        'ရန်ကုန်': 'ygn',
        'မန္တလေး': 'mdy',
        'နေပြည်တော်': 'npt',
        'ပဲခူး': 'bgo',
        'စစ်ကိုင်း': 'sgg',
        'မကွေး': 'mgw',
        'ဧရာဝတီ': 'ayd',
        'တနင်္သာရီ': 'tnt',
        'မွန်': 'mon',
        'ရှမ်း': 'shn',
        'ကချင်': 'kch',
        'ကယား/ကရင်နီ': 'kyh',
        'ကရင်': 'kyn',
        'ချင်း': 'chn',
        'ရခိုင်': 'rkh',
        'အခြား': 'othr',
        # Keep English versions for backward compatibility
        'Yangon': 'ygn',
        'Mandalay': 'mdy',
        'Naypyidaw': 'npt',
        'Bago': 'bgo',
        'Sagaing': 'sgg',
        'Magway': 'mgw',
        'Ayeyarwady': 'ayd',
        'Tanintharyi': 'tnt',
        'Mon': 'mon',
        'Shan': 'shn',
        'Kachin': 'kch',
        'Kayah': 'kyh',
        'Kayin': 'kyn',
        'Chin': 'chn',
        'Rakhine': 'rkh',
        'Other Location': 'othr'
    }
    
    prefix = location_prefixes.get(location, 'othr')
    context.user_data['case_prefix'] = prefix
    
    # Initialize the form data dictionary
    context.user_data['form_data'] = {}
    
    # Remove keyboard to hide location selector buttons
    reply_markup = ReplyKeyboardRemove()
    
    # Get the appropriate instructions and example based on report type
    if context.user_data['report_type'] == 'Missing Person (Earthquake)':
        instructions = (
            "ပျောက်ဆုံးနေသူနှင့် ပတ်သက်သည့် အချက်အလက်များကို ဖြည့်စွက်ပေးပါ။\n"
            "1. အမည်အပြည့်အစုံ\n"
            "2. အသက်\n"
            "3. ကျား/မ\n"
            "4. နောက်ဆုံးတွေ့ရှိခဲ့သည့်နေရာ (အသေးစိတ်ဖော်ပြပါ)\n"
            "5. ကိုယ်ခန္ဓာဖော်ပြချက်\n"
            "6. နောက်ဆုံးတွေ့ရှိခဲ့သည့်အချိန် (ရက်စွဲ/အချိန်)\n"
            "7. သင့်ဆက်သွယ်ရန်အချက်အလက်"
        )
        
        # Add example for Mandalay
        if location == "မန္တလေး":
            example = (
                "\nဥပမာ:\n"
                "1. မင်းမင်း\n"
                "2. ၃၀ နှစ်\n"
                "3. ကျား\n"
                "4. ၈၆ လမ်း၊ ၃၈ နှင့် ၃၉ လမ်းကြား၊ မန္တလေးမြို့\n"
                "5. အရပ် ၅ပေ ၇လက်မ၊ ဆံပင်အတို၊ မျက်မှန်တပ်ထားသူ၊ စကတ်အိတ်ပါသော အနက်ရောင်ဘောင်းဘီဝတ်ဆင်ထားသူ\n"
                "6. မတ်လ ၃၀ ရက်၊ ၂၀၂၅၊ နံနက် ၉နာရီ\n"
                "7. ဖုန်း - ၀၉၁၂၃၄၅၆၇၈၉၊ ညီမဖြစ်သူမှ ဆက်သွယ်ခြင်း"
            )
        else:
            example = (
                "\nဥပမာ:\n"
                "1. မောင်အောင်\n"
                "2. ၂၅ နှစ်\n"
                "3. ကျား\n" 
                f"4. {location} မြို့ (တိကျသော လိပ်စာဖော်ပြပါ)\n"
                "5. အရပ် ၅ပေ ၉လက်မ၊ ဆံပင်အနက်၊ ဂျင်းဘောင်းဘီအပြာနှင့် တီရှပ်အနက်ဝတ်ဆင်ထားသူ\n"
                "6. မတ်လ ၃၀ ရက်၊ ၂၀၂၅၊ နံနက် ၁၀နာရီ\n"
                "7. ဖုန်း - ၀၉၅၅၅၁၂၃၄၅၆၊ ညီအစ်ကိုဖြစ်သူမှ ဆက်သွယ်ခြင်း"
            )
        
        await update.message.reply_text(
            f"တည်နေရာ {location} အတွက် သင့်အစီရင်ခံစာကို စတင်ပါပြီ။\n\n"
            f"{instructions}\n{example}",
            reply_markup=reply_markup
        )
        
    elif context.user_data['report_type'] == 'Request Rescue':
        instructions = (
            "ကယ်ဆယ်ရေးအတွက် အောက်ပါအချက်အလက်များကို ပေးပါ -\n"
            "1. ပိတ်မိနေသူ အရေအတွက်\n"
            "2. တိကျသော လိပ်စာ/တည်နေရာ\n"
            "3. အဆောက်အအုံအခြေအနေ\n"
            "4. ဒဏ်ရာရရှိမှုရှိပါသလား?\n"
            "5. အရေးပေါ်လိုအပ်ချက်များ (ဆေးဝါး၊ ရေ၊ အစားအစာ)\n"
            "6. သင့်အမည်နှင့် ပိတ်မိနေသူများနှင့် ဆက်နွယ်မှု\n"
            "7. အခြားဆက်သွယ်ရန်နည်းလမ်း"
        )
        
        # Add example for Mandalay
        if location == "မန္တလေး":
            example = (
                "\nဥပမာ:\n"
                "1. ၃ ဦး (လူကြီး ၂ ဦး၊ ကလေး ၁ ဦး)\n"
                "2. အမှတ် ၄၅၆၊ ၃၅ လမ်း၊ ၇၆ နှင့် ၇၇ လမ်းကြား၊ မန္တလေးမြို့\n"
                "3. နှစ်ထပ်အဆောက်အအုံ၏ ပထမထပ်တွင် ပိတ်မိနေပြီး လှေကားပြိုကျ၍ ထွက်မရပါ\n"
                "4. ကလေးမှာ ခြေတွင် ဒဏ်ရာအနည်းငယ်ရထားပါသည်၊ အခြားသူများမှာ ဒဏ်ရာမရှိပါ\n"
                "5. ရေနှင့် ကလေးအတွက် ဆေးဝါးလိုအပ်ပါသည်\n"
                "6. ကျွန်ုပ်အမည် - မင်းမင်း၊ မိသားစုဝင်များနှင့်အတူရှိ\n"
                "7. ဖုန်း - ၀၉၁၂၃၄၅၆၇၈၉ (ချိတ်ဆက်မှုအားနည်းပါသည်)"
            )
        else:
            example = (
                "\nဥပမာ:\n"
                "1. ၄ ဦး (လူကြီး ၂ ဦး၊ ကလေး ၂ ဦး)\n"
                f"2. {location} မြို့ (တိကျသော လိပ်စာဖော်ပြပါ)\n"
                "3. အဆောက်အအုံ တစ်စိတ်တစ်ပိုင်း ပြိုကျထား၊ လှေကားကို အပျက်အစီးများက ပိတ်ဆို့နေ\n"
                "4. အသက်ကြီးသော အမျိုးသမီးတစ်ဦးမှာ နှလုံးရောဂါရှိ၍ ဆေးလိုအပ်ပါသည်\n"
                "5. ရေ၊ အစားအစာနှင့် ဆေးဝါးအကူအညီလိုအပ်ပါသည်\n"
                "6. ကျွန်ုပ်အမည် - ကိုဝင်း၊ မိသားစုဝင်များနှင့်အတူရှိ\n"
                "7. ဖုန်း - ၀၉၈၇၆၅၄၃၂၁၀ (ချိတ်ဆက်မှုအားနည်းပါသည်)"
            )
        
        await update.message.reply_text(
            f"တည်နေရာ {location} အတွက် သင့်ကယ်ဆယ်ရေးတောင်းဆိုချက်ကို စတင်ပါပြီ။\n\n"
            f"{instructions}\n{example}",
            reply_markup=reply_markup
        )
    
    return COLLECTING_DATA

async def collect_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store all provided data at once and ask for urgency level, with validation."""
    user_input = update.message.text
    
    # Get expected format for this report type
    report_type = context.user_data.get('report_type', '')
    expected_format = get_instructions_by_type(report_type)
    
    # Validate input
    if not validate_report_data(user_input, report_type):
        # If input is too short or looks like a greeting/simple message
        await update.message.reply_text(
            "❌ Your information appears to be incomplete or in the wrong format.\n\n"
            "သင့်အချက်အလက်သည် မပြည့်စုံဟုထင်ရပါသည်။\n\n"
            "Please provide complete information as shown in the example:\n"
            "ကျေးဇူးပြု၍ ဥပမာပြထားသည့်အတိုင်း အချက်အလက်အပြည့်အစုံကို ပေးပါ။\n\n"
            f"{expected_format}"
        )
        # Stay in the current state to let them try again
        return COLLECTING_DATA
    
    # Valid data - proceed normally
    context.user_data['all_data'] = user_input
    
    # Generate a unique report ID with location prefix if available
    prefix = context.user_data.get('case_prefix', '')
    if prefix:
        report_id = f"{prefix.upper()}-{str(uuid.uuid4())[:6].upper()}"
    else:
        report_id = str(uuid.uuid4())[:8].upper()
        
    context.user_data['report_id'] = report_id
    
    # Create urgency selection keyboard
    keyboard = [
        ["အလွန်အရေးပေါ် (ဆေးကုသမှု လိုအပ်)"],
        ["အရေးပေါ် (ပိတ်မိနေ/ပျောက်ဆုံး)"],
        ["အလယ်အလတ် (လုံခြုံသော်လည်း ကွဲကွာနေ)"],
        ["အရေးမကြီး (သတင်းအချက်အလက်သာ)"]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=True, 
        resize_keyboard=True
    )

    await update.message.reply_text(
        f"အချက်အလက်များ ပေးပို့သည့်အတွက် ကျေးဇူးတင်ပါသည်။ သင့် အစီရင်ခံစာ ID မှာ: *{report_id}*\n\n"
        "သင့် အစီရင်ခံစာ၏ အရေးပေါ်အဆင့်ကို ရွေးချယ်ပါ:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return SELECT_URGENCY

def validate_report_data(text: str, report_type: str) -> bool:
    """
    Validate that the provided text contains appropriate report information.
    More lenient approach to allow valid submissions.
    
    Args:
        text: The text to validate
        report_type: The type of report expected
        
    Returns:
        True if the text appears to be valid report data, False otherwise
    """
    # Skip validation if report_type is not set
    if not report_type:
        return True
        
    # Check for extremely short inputs or just a few words
    if len(text) < 25:  # Reduced from 50 to 25 characters
        return False
    
    # If the text contains just a few words, it's probably not valid
    word_count = len(text.split())
    if word_count < 4:  # Reduced from 5 to 4 words
        return False
    
    # Check for common greetings or simple messages that are definitely not reports
    common_greetings = [
        "hello", "hi", "hey", "how are you", "test", "what", "why", 
        "good morning", "good afternoon", "good evening", "help", "ဟယ်လို", 
        "မင်္ဂလာပါ", "နေကောင်းလား", "ဘယ်လိုလဲ", "အကူအညီလိုတယ်", "စမ်းကြည့်တာ"
    ]
    
    # Only reject if the text is exactly one of these greetings
    if text.lower().strip() in common_greetings:
        return False
    
    # For all report types, simply check if there are multiple lines (as in a form response)
    # or if the text is long enough to be a detailed description
    if text.count('\n') >= 2 or len(text) > 100:
        return True
    
    # Check for numeric content which is likely to be in all valid reports
    if bool(re.search(r'\d', text)):
        return True
    
    # More lenient keyword check - if it contains any potentially relevant words based on type
    if "Missing Person" in report_type:
        keywords = ["အမည်", "နာမည်", "အသက်", "ကျား", "မ", "တွေ့", "နေရာ", "ပျောက်", 
                   "name", "age", "male", "female", "location", "last seen", "missing"]
    elif "Found Person" in report_type:
        keywords = ["တွေ့", "ရှိ", "အသက်", "ကျား", "မ", "နေရာ", "အခြေအနေ",
                   "found", "location", "condition", "age", "male", "female"]
    elif "Request Rescue" in report_type:
        keywords = ["ကယ်", "အကူအညီ", "တည်နေရာ", "လိပ်စာ", "ဒဏ်ရာ", "ပိတ်မိ", "အရေအတွက်",
                   "rescue", "help", "location", "address", "injured", "trapped", "count", "people"]
    elif "Offer Help" in report_type:
        keywords = ["ကူညီ", "အကူအညီ", "ပေး", "တည်နေရာ", "ရရှိနိုင်", 
                   "help", "offer", "provide", "location", "available"]
    else:
        # For other types, be more lenient
        return True
    
    # Check if ANY of the keywords match, not requiring multiple matches
    for keyword in keywords:
        if keyword.lower() in text.lower():
            return True
    
    # If we get here, the text doesn't contain any relevant keywords
    # But we'll still return True if it's a medium-length message that might be a valid report
    if len(text) > 75:  # A reasonably long message is likely a report
        return True
        
    # If we reach here, reject the input
    return False

async def select_urgency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the selection of urgency level with validation."""
    selected_urgency = update.message.text
    
    # Map Burmese urgency levels to English for database storage
    urgency_map = {
        "အလွန်အရေးပေါ် (ဆေးကုသမှု လိုအပ်)": "Critical (Medical Emergency)",
        "အရေးပေါ် (ပိတ်မိနေ/ပျောက်ဆုံး)": "High (Trapped/Missing)",
        "အလယ်အလတ် (လုံခြုံသော်လည်း ကွဲကွာနေ)": "Medium (Safe but Separated)",
        "အရေးမကြီး (သတင်းအချက်အလက်သာ)": "Low (Information Only)",
        # Keep English versions for backward compatibility
        "Critical (Medical Emergency)": "Critical (Medical Emergency)",
        "High (Trapped/Missing)": "High (Trapped/Missing)",
        "Medium (Safe but Separated)": "Medium (Safe but Separated)",
        "Low (Information Only)": "Low (Information Only)"
    }
    
    # Check if the selection is valid
    if selected_urgency not in urgency_map:
        # Show the keyboard again with a message
        keyboard = [
            ["အလွန်အရေးပေါ် (ဆေးကုသမှု လိုအပ်)"],
            ["အရေးပေါ် (ပိတ်မိနေ/ပျောက်ဆုံး)"],
            ["အလယ်အလတ် (လုံခြုံသော်လည်း ကွဲကွာနေ)"],
            ["အရေးမကြီး (သတင်းအချက်အလက်သာ)"]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard, 
            one_time_keyboard=True, 
            resize_keyboard=True
        )
        
        await update.message.reply_text(
            "❌ ကျေးဇူးပြု၍ အောက်ပါ အရေးပေါ်အဆင့်များမှ တစ်ခုကို ရွေးချယ်ပါ:\n\n"
            "Please select one of the urgency levels from the keyboard below:",
            reply_markup=reply_markup
        )
        return SELECT_URGENCY
    
    # Store the mapped urgency
    context.user_data['urgency'] = urgency_map.get(selected_urgency, selected_urgency)
    
    # Create a keyboard with a skip button for photo
    keyboard = [[
        "ဓာတ်ပုံ မရှိပါ"  # "Skip Photo" in Burmese
    ]]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=True, 
        resize_keyboard=True
    )
    
    await update.message.reply_text(
        "အရေးပေါ်အဆင့် သတ်မှတ်ပြီးပါပြီ။\n\n"
        "📸 ဓာတ်ပုံရှိပါက ယခုပေးပို့နိုင်ပါသည်။\n"
        "မရှိပါက 'ဓာတ်ပုံ မရှိပါ' ခလုတ်ကိုနှိပ်ပါ။",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return PHOTO


async def finalize_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finalize and save the report to the database"""
    try:
        user_data = context.user_data
        
        # Prepare report data - Make sure all fields are properly initialized
        report_data = {
            'report_id': user_data.get('report_id', ''),
            'report_type': user_data.get('report_type', ''),
            'all_data': user_data.get('all_data', ''),
            'urgency': user_data.get('urgency', ''),
            'photo_id': user_data.get('photo_id', None),  # Keep Telegram file_id
            'photo_url': user_data.get('photo_url', None),  # Add DO Spaces URL
            'photo_path': user_data.get('photo_path', None),  # Add DO Spaces path
            'location': user_data.get('location', 'Unknown'),
            'status': 'Still Missing',  # Set a proper default status for new reports
        }
        
        # Get telegram user object
        telegram_user = update.effective_user
        
        # Log the data being saved for debugging
        logger.info(f"Saving report with ID: {report_data['report_id']}")
        logger.debug(f"Report data: {report_data}")
        
        try:
            # Save to database
            report = save_report(report_data, telegram_user)
            
            if not report:
                # If database save fails, store in memory as fallback
                logger.warning(f"Database save failed, storing report {report_data['report_id']} in memory")
                # Get current time in Myanmar timezone
                myanmar_tz = pytz.timezone('Asia/Yangon')
                timestamp = datetime.now(myanmar_tz).isoformat()
                store_report(report_data['report_id'], user_data, telegram_user, timestamp)
                
                await update.message.reply_text(
                    f"⚠️ Database connection issue, but your report is stored temporarily.\n\n"
                    f"Report ID: `{report_data['report_id']}`\n\n"
                    f"Please save this ID. We'll transfer your report to the database once connection is restored.\n\n"
                    f"သင့်အစီရင်ခံစာကို ယာယီသိမ်းဆည်းထားပါသည်။ ဤID ကို သိမ်းဆည်းထားပါ။",
                    parse_mode='MARKDOWN'
                )
                
                try:
                    # Try to send to channel even if database save failed
                    priority_icon = PRIORITIES.get(user_data['urgency'], "⚪")
                    # Format time in Myanmar timezone
                    timestamp = datetime.now(myanmar_tz).strftime("%Y-%m-%d %H:%M:%S")
                    safe_message = format_report_message(user_data, report_data['report_id'], priority_icon, timestamp, telegram_user)

                    await send_report_to_channel(context.bot, user_data, safe_message)
                except Exception as channel_error:
                    logger.error(f"Error sending report to channel: {str(channel_error)}")
                    
                # Show menu after short delay even if DB save failed
                await asyncio.sleep(2)
                await show_main_menu(update, context)
                    
                return CHOOSING_REPORT_TYPE
            
            # Include report ID in response with improved formatting
            report_id = report_data['report_id']
            response = (
                f"✅ *YOUR REPORT HAS BEEN SUBMITTED SUCCESSFULLY!*\n\n"
                f"📝 Report ID: `{report_id}`\n\n"
                f"⚠️ *PLEASE SAVE THIS ID FOR FUTURE REFERENCE*\n\n"
                f"သင့်အစီရင်ခံစာကို အောင်မြင်စွာ တင်သွင်းပြီးပါပြီ။\n\n"
                f"အစီရင်ခံစာ ID: `{report_id}`\n\n"
                f"နောင်တွင် အသုံးပြုရန် ဤ ID ကို သိမ်းဆည်းထားပါ။"
            )
            
            await update.message.reply_text(response, parse_mode='MARKDOWN')
            
            # Send to channel with improved formatting
            try:
                priority_icon = PRIORITIES.get(user_data['urgency'], "⚪")
                # Get current time in Myanmar timezone
                myanmar_tz = pytz.timezone('Asia/Yangon')
                timestamp = datetime.now(myanmar_tz).strftime("%Y-%m-%d %H:%M:%S")
                safe_message = format_report_message(user_data, report_id, priority_icon, timestamp, telegram_user)
                await send_report_to_channel(context.bot, user_data, safe_message)
            except Exception as channel_error:
                logger.error(f"Error sending report to channel: {str(channel_error)}")
            
            # Clear only the report-specific data, but keep the conversation flag
            for key in list(context.user_data.keys()):
                if key != 'in_conversation':
                    context.user_data.pop(key, None)
        
            # Set the conversation flag again to be sure
            context.user_data['in_conversation'] = True
            
            # Show main menu after a short delay to allow user to read the confirmation
            await asyncio.sleep(2)
            await show_main_menu(update, context)
            
            return CHOOSING_REPORT_TYPE
        except Exception as e:
            logger.error(f"Error saving report: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "❌ Error saving your report. Please try again later.\n\n"
                "သင့်အစီရင်ခံစာကို မသိမ်းဆည်းနိုင်ပါ။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error in finalize_report: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "❌ An unexpected error occurred. Please try again later.\n\n"
            "မမျှော်လင့်ထားသော အမှားတစ်ခု ဖြစ်ပေါ်ခဲ့သည်။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"
        )
        return ConversationHandler.END

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the photo in Digital Ocean S3 and finalize the report."""
    try:
        # Check if we received a photo
        if update.message.photo:
            # Acknowledge receipt first to improve user experience
            await update.message.reply_text(
                "✅ Photo received! Processing your photo and report..."
            )
            
            # Get the largest available photo (best quality)
            photo_file = update.message.photo[-1]
            file_id = photo_file.file_id
            
            # Log the original file_id for debugging
            logger.info(f"Received photo with file_id: {file_id} for report ID: {context.user_data.get('report_id')}")
            
            # Download the photo file
            photo_obj = await context.bot.get_file(file_id)
            photo_bytes_io = io.BytesIO()
            await photo_obj.download_to_memory(photo_bytes_io)
            photo_bytes_io.seek(0)  # Reset pointer to beginning of file
            
            # Generate a unique filename
            report_id = context.user_data.get('report_id', '')
            photo_filename = f"{report_id}_{uuid.uuid4()}.jpg"
            
            try:
                # Get S3 client
                s3_client = get_s3_client()
                
                if not s3_client:
                    # Fall back to just using Telegram's file_id if S3 client creation fails
                    logger.warning("S3 client could not be created, using Telegram storage only")
                    context.user_data['photo_id'] = file_id
                    context.user_data['photo_url'] = None
                    context.user_data['photo_path'] = None
                else:
                    # Upload to DO Spaces
                    bucket_name = os.environ.get('DO_SPACES_BUCKET', 'photos')
                    photo_bytes_io.seek(0)  # Ensure we're at the beginning of the file
                    
                    # Log upload attempt
                    logger.info(f"Uploading photo {photo_filename} to DO Spaces bucket '{bucket_name}'")
                    
                    # Explicit ACL and content type settings
                    try:
                        s3_client.upload_fileobj(
                            photo_bytes_io,
                            bucket_name,
                            photo_filename,
                            ExtraArgs={
                                'ACL': 'public-read',
                                'ContentType': 'image/jpeg'
                            }
                        )
                        
                        # Generate the public URL
                        endpoint_url = os.environ.get('DO_SPACES_ENDPOINT', '').rstrip('/')
                        photo_url = f"{endpoint_url}/{bucket_name}/{photo_filename}"
                        
                        logger.info(f"Uploaded photo to Digital Ocean, URL: {photo_url}")
                        
                        # Store both the original file_id (for Telegram) and the DO Spaces URL
                        context.user_data['photo_id'] = file_id
                        context.user_data['photo_url'] = photo_url 
                        context.user_data['photo_path'] = f"{bucket_name}/{photo_filename}"
                    except Exception as upload_err:
                        logger.error(f"S3 upload error: {str(upload_err)}", exc_info=True)
                        # Fall back to just using Telegram's file_id
                        context.user_data['photo_id'] = file_id
                        context.user_data['photo_url'] = None
                        context.user_data['photo_path'] = None
            
            except Exception as upload_error:
                logger.error(f"Failed to upload photo to Digital Ocean: {str(upload_error)}", exc_info=True)
                # Fall back to just using Telegram's file_id
                context.user_data['photo_id'] = file_id
                context.user_data['photo_url'] = None
                context.user_data['photo_path'] = None
                
                await update.message.reply_text(
                    "⚠️ Could not upload photo to cloud storage, but will continue with report submission using Telegram's storage."
                )
            
            # Remove keyboard
            reply_markup = ReplyKeyboardRemove()
            
            # Acknowledge success and continue
            await update.message.reply_text(
                "✅ Photo processed! Finalizing your report...",
                reply_markup=reply_markup
            )
            
            # Continue to finalization
            return await finalize_report(update, context)
        else:
            # If somehow this handler was called but no photo is present
            logger.error("Photo handler called but no photo found in the message")
            await update.message.reply_text(
                "❌ No photo detected. Please send a photo or click 'Skip Photo'."
            )
            return PHOTO
    except Exception as e:
        logger.error(f"Error processing photo: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "❌ There was an error processing your photo. Please try again or use 'Skip Photo'."
        )
        return PHOTO

async def handle_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle skipping the photo."""
    try:
        # Check if the user clicked the skip button or typed "skip"
        user_input = update.message.text.strip()
        
        logger.info(f"Photo skip handler received: {user_input}")
        
        # Allow either "skip" (typed) or "Skip Photo" (button press) or Burmese version
        if (user_input.lower() == "skip" or 
            user_input == "Skip Photo" or 
            user_input == "ဓာတ်ပုံ မရှိပါ"):
            
            # Set no photo indicator
            context.user_data['photo_id'] = None
            
            # Remove keyboard
            reply_markup = ReplyKeyboardRemove()
            await update.message.reply_text(
                "ဓာတ်ပုံကို ကျော်သွားပါမည်...",
                reply_markup=reply_markup
            )
            
            # Return to main flow
            return await finalize_report(update, context)
        else:
            # User input something else - ask again
            keyboard = [[
                "ဓာတ်ပုံ မရှိပါ"  # Skip Photo in Burmese
            ]]
            reply_markup = ReplyKeyboardMarkup(
                keyboard, 
                one_time_keyboard=True, 
                resize_keyboard=True
            )
            
            await update.message.reply_text(
                "ဓာတ်ပုံပေးပို့ပါ သို့မဟုတ် 'ဓာတ်ပုံ မရှိပါ' ခလုတ်ကိုနှိပ်ပါ။",
                reply_markup=reply_markup
            )
            
            # Stay in the same state
            return PHOTO
    except Exception as e:
        logger.error(f"Error in handle_skip_photo: {str(e)}")
        await update.message.reply_text(
            "❌ အမှားတစ်ခု ဖြစ်ပွားခဲ့သည်။ ထပ်မံကြိုးစားပါ သို့မဟုတ် /cancel သုံးပြီး အစကနေစတင်ပါ။"
        )
        return PHOTO

async def search_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for a report by ID with improved formatting"""
    report_id = update.message.text.strip()
    
    try:
        logger.info(f"Searching for report with ID: {report_id}")
        
        # Get report from database
        report = await get_report(report_id)
        
        if not report:
            # Check in-memory backup
            if report_id in REPORTS:
                report = REPORTS[report_id]
            
            logger.info(f"No report found with ID: {report_id}")
            await update.message.reply_text(
                "❌ No report found with that ID. Please check and try again.\n\n"
                "ထို ID ဖြင့် အစီရင်ခံစာ မတွေ့ရှိပါ။ စစ်ဆေးပြီး ထပ်စမ်းကြည့်ပါ။"
            )
            return ConversationHandler.END
        
        # Log the report data structure for debugging
        logger.info(f"Report found: {type(report)} with keys: {report.keys() if isinstance(report, dict) else 'Not a dict'}")
        
        # Convert created_at to Myanmar timezone if it exists
        created_at = report.get('created_at', 'N/A')
        if created_at != 'N/A':
            try:
                if isinstance(created_at, str):
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    dt = created_at
                
                # If timezone info not present, assume UTC and convert to Myanmar timezone
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC)
                
                myanmar_tz = pytz.timezone('Asia/Yangon')
                dt = dt.astimezone(myanmar_tz)
                created_at = dt.strftime("%Y-%m-%d %H:%M:%S") + " (Asia/Yangon)"
            except Exception as e:
                logger.error(f"Error converting timestamp to Myanmar timezone: {str(e)}")
        
        # Format the response with improved readability
        response = f"📋 *REPORT DETAILS:*\n\n"
        response += f"📝 *Type:* {report.get('report_type', 'N/A')}\n\n"
        response += f"📍 *Location:* {report.get('location', 'N/A')}\n\n"
        response += f"ℹ️ *Details:*\n{report.get('all_data', 'N/A')}\n\n"
        
        # Add appropriate emoji for urgency level
        urgency = report.get('urgency', 'N/A')
        urgency_emoji = "🔴" if "Critical" in urgency else "🟠" if "High" in urgency else "🟡" if "Medium" in urgency else "🟢"
        response += f"{urgency_emoji} *Urgency:* {urgency}\n\n"
        
        # Add status if available
        status = report.get('status')
        if not status or status == 'No status set' or status == 'N/A':
            status = "Still Missing"
            # Update the in-memory version if this is the source
            if report_id in REPORTS:
                REPORTS[report_id]['status'] = status
                
        status_emoji = "🔍" if "Missing" in status else "✅" if "Found" in status else "🏥" if "Hospitalized" in status else "⚫" if "Deceased" in status else "❓"
        response += f"{status_emoji} *Status:* {status}\n\n"
        
        response += f"⏰ *Submitted:* {created_at}\n"
        
        await update.message.reply_text(response, parse_mode='MARKDOWN')
        
        # If there's a photo, send it too
        photo_id = report.get('photo_id')
        photo_url = report.get('photo_url')

        if photo_url:
            # Add the photo URL to the response
            await update.message.reply_text(f"📷 *Photo:* [View Photo]({photo_url})", parse_mode='MARKDOWN')
            
        if photo_id:
            try:
                # Try to send the photo directly using Telegram's storage
                await update.message.reply_photo(photo_id)
            except Exception as photo_error:
                logger.error(f"Error sending photo: {str(photo_error)}")
                if photo_url:
                    await update.message.reply_text(
                        f"📷 This report has a photo that can be viewed at: {photo_url}"
                    )
                else:
                    await update.message.reply_text(
                        "📷 This report has a photo but it could not be displayed."
                    )
        
        # Show main menu after displaying report
        await asyncio.sleep(2)
        await show_main_menu(update, context)
        
        return CHOOSING_REPORT_TYPE
    except Exception as e:
        logger.error(f"Error in search_report: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "❌ An error occurred while retrieving the report information. Please try again later."
        )
        return ConversationHandler.END

async def send_message_to_submitter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a message to the submitter of a report."""
    try:
        if 'contact_report_id' not in context.user_data:
            report_id = update.message.text.strip().upper()
            
            try:
                # Get report from database (using get_report instead of get_report_by_id for consistency)
                report = await get_report(report_id)
                
                if not report:
                    # Check in-memory backup
                    if report_id in REPORTS:
                        # Use in-memory data if available
                        memory_report = REPORTS[report_id]
                        user_id = memory_report.get('user_id')
                        if not user_id:
                            await update.message.reply_text(
                                f"❌ No user ID associated with in-memory report {report_id}. Cannot send message."
                            )
                            return ConversationHandler.END
                            
                        context.user_data['contact_report_id'] = report_id
                        context.user_data['contact_user_id'] = user_id
                        
                        await update.message.reply_text(
                            f"✅ Report found in temporary storage! Please type your message to send to the submitter of report {report_id}:"
                        )
                        return DESCRIPTION
                    
                    # No report found in DB or memory
                    logger.warning(f"No report found with ID: {report_id}")
                    await update.message.reply_text(
                        f"❌ No report found with ID: {report_id}. Please check the ID and try again."
                    )
                    return ConversationHandler.END
                
                # Report found in database
                user_id = report.get('user_id')
                if not user_id:
                    logger.warning(f"Report {report_id} found but no user_id associated")
                    await update.message.reply_text(
                        f"❌ No user ID associated with report {report_id}. Cannot send message to the submitter."
                    )
                    return ConversationHandler.END
                    
                context.user_data['contact_report_id'] = report_id
                context.user_data['contact_user_id'] = user_id
                
                logger.info(f"Found report {report_id} with user_id {user_id}, proceeding to message step")
                await update.message.reply_text(
                    f"✅ Report found! Please type your message to send to the submitter of report {report_id}:"
                )
                return DESCRIPTION
                
            except Exception as e:
                logger.error(f"Error finding report submitter: {str(e)}", exc_info=True)
                await update.message.reply_text(
                    f"❌ Error finding report with ID: {report_id}. Please try again later."
                )
                return ConversationHandler.END
        else:
            # Get the message content
            message_text = update.message.text
            report_id = context.user_data['contact_report_id']
            user_id = context.user_data['contact_user_id']
            
            try:
                # Forward the message to the report submitter
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"*Message regarding your report {report_id}*:\n\n{message_text}\n\n"
                         f"From: {update.effective_user.first_name} {update.effective_user.last_name or ''}",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Confirm to the sender
                await update.message.reply_text(
                    f"✅ Your message has been sent to the submitter of report {report_id}."
                )
            except Exception as e:
                logger.error(f"Error sending message to submitter: {str(e)}")
                await update.message.reply_text(
                    "❌ There was an error sending your message. The user may have blocked the bot."
                )
            
            # Clear the data and end the conversation
            context.user_data.clear()
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error in send_message_to_submitter: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "❌ An unexpected error occurred. Please try again or use /start to begin a new operation."
        )
        return ConversationHandler.END

async def search_missing_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for missing persons based on name or details"""
    search_term = update.message.text.strip()
    
    # Search in database
    results = await search_missing_people(search_term)
    
    if not results:
        await update.message.reply_text(
            "❌ No missing persons found matching your search criteria.\n\n"
            "သင့်ရှာဖွေမှုနှင့် ကိုက်ညီသည့် ပျောက်ဆုံးနေသူများ မတွေ့ရှိပါ။"
        )
        return ConversationHandler.END
    
    # Show results
    response = f"🔍 *Search Results:*\nFound {len(results)} matching records.\n\n"
    
    for i, report in enumerate(results, 1):
        # Extract name if possible
        name = "Unknown"
        all_data = report.get('all_data', '')
        lines = all_data.split('\n')
        for line in lines:
            if line.startswith("1.") or "name" in line.lower():
                name = line.split(":", 1)[1].strip() if ":" in line else line.split(".", 1)[1].strip() if "." in line else line
                break
        
        response += f"{i}. *{name}*\n"
        response += f"   Location: {report.get('location', 'N/A')}\n"
        response += f"   Report ID: `{report.get('report_id')}`\n\n"
    
    response += "To view full details of a report, search by its ID using 'Search Reports by ID'."
    
    await update.message.reply_text(response, parse_mode='MARKDOWN')
    return CHOOSING_REPORT_TYPE        

async def choose_report_to_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Let the user choose which report submitter to contact."""
    selection = update.message.text.strip()
    
    try:
        index = int(selection) - 1
        matching_reports = context.user_data.get('matching_reports', [])
        
        if 0 <= index < len(matching_reports):
            selected_report = matching_reports[index]
            report_id = selected_report['report_id']
            user_id = selected_report['user_id']
            
            context.user_data['contact_report_id'] = report_id
            context.user_data['contact_user_id'] = user_id
            
            # Get more details about the person
            person_details = ""
            if 'all_data' in selected_report:
                # Extract name if possible
                lines = selected_report['all_data'].split('\n')
                for line in lines:
                    if line.lower().startswith("1.") or "name" in line.lower():
                        person_details = line
                        break
            
            await update.message.reply_text(
                f"You're contacting the submitter of report `{report_id}`\n"
                f"{person_details}\n\n"
                f"Please write your message. Include your contact information if you want a direct response:",
                parse_mode=ParseMode.MARKDOWN
            )
            return DESCRIPTION
        else:
            await update.message.reply_text(
                "Invalid selection. Please choose a number from the list or use /cancel to cancel."
            )
            return SEND_MESSAGE_TO_REPORTER
    except ValueError:
        await update.message.reply_text(
            "Please enter a number corresponding to the report you want to contact."
        )
        return SEND_MESSAGE_TO_REPORTER

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the main menu after report completion"""
    keyboard = [
        ['လူပျောက်တိုင်မယ်', 'သတင်းပို့မယ်'],
        ['အကူအညီတောင်းမယ်', 'အကူအညီပေးမယ်'],
        ['ID နဲ့ လူရှာမယ်', 'သတင်းပို့သူ ကို ဆက်သွယ်ရန်'],
        ['နာမည်နဲ့ လူပျောက်ရှာမယ်', 'အစီရင်ခံစာအခြေအနေပြင်ဆင်မယ်']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=False, resize_keyboard=True)

    await update.message.reply_text(
        "ဆက်လက်၍ မည်သည့်လုပ်ဆောင်ချက်ကို လုပ်ဆောင်လိုပါသလဲ?",
        reply_markup=reply_markup
    )
    
    # Return to CHOOSING_REPORT_TYPE state to handle the next menu selection
    return CHOOSING_REPORT_TYPE


# Helper functions
def get_instructions_by_type(report_type):
    """Return instructions based on report type."""
    instructions = {
        "Missing Person (Earthquake)": (
            "*လူပျောက်အစီရင်ခံစာ*\n\n"
            "ကျေးဇူးပြု၍ အောက်ပါအချက်အလက်များကို တစ်ခုတည်းသော စာတစ်စောင်တွင် ပေးပို့ပါ -\n\n"
            "1. ပျောက်ဆုံးသူအမည်\n"
            "2. အသက်\n"
            "3. ကျား/မ\n"
            "4. ကိုယ်ခန္ဓာဖော်ပြချက် (အရပ်၊ ကိုယ်ခန္ဓာဖွဲ့စည်းပုံ၊ ဝတ်ဆင်ထားသော အဝတ်အစား စသည်)\n"
            "5. နောက်ဆုံးတွေ့ရှိခဲ့သည့်နေရာ (တတ်နိုင်သမျှ တိကျစွာ ဖော်ပြပါ)\n"
            "6. နောက်ဆုံးတွေ့ရှိခဲ့သည့်အချိန် (ရက်စွဲ/အချိန်)\n"
            "7. ဆေးဝါးအခြေအနေ သို့မဟုတ် အထူးလိုအပ်ချက်များ\n"
            "8. သင့်ဆက်သွယ်ရန်အချက်အလက်\n\n"
            "*ဥပမာ:*\n"
            "1. အောင်ကို\n"
            "2. ၃၅\n"
            "3. ကျား\n" 
            "4. အရပ်မြင့် (၅ပေ ၁၀လက်မ)၊ ပိန်ပိန်ပါး၊ ဆံပင်အမည်း၊ ဂျင်းဘောင်းဘီ အပြာနှင့် တီရှပ်အနီဝတ်ဆင်ထား\n"
            "5. နောက်ဆုံး ဆူးလေစတုရန်းမော်လ် ဒုတိယထပ် စားသောက်ဆိုင်အနီးတွင် တွေ့ရှိခဲ့\n"
            "6. နိုဝင်ဘာ ၂၆၊ ၂၀၂၃ - ညနေ ၂:၃၀ ခန့်\n"
            "7. ဆီးချိုရောဂါရှိ၊ ပုံမှန်ဆေးသောက်ရန်လို\n"
            "8. ဆက်သွယ်ရန် - သူသူ (ညီမ) - ၀၉၁၂၃၄၅၆၇၈၉\n\n"
            "*မှတ်ချက်:* နောက်အဆင့်တွင် ဓာတ်ပုံထည့်သွင်းနိုင်ပါသည်။"
        ),
        "Found Person (Earthquake)": (
            "*လူတွေ့ရှိမှု အစီရင်ခံစာ*\n\n"
            "ကျေးဇူးပြု၍ အောက်ပါအချက်အလက်များကို တစ်ခုတည်းသော စာတစ်စောင်တွင် ပေးပို့ပါ -\n\n"
            "1. တွေ့ရှိသူ၏ အမည် (သိရှိပါက)\n"
            "2. ခန့်မှန်းအသက်\n"
            "3. ကျား/မ\n"
            "4. ကိုယ်ခန္ဓာဖော်ပြချက် (အရပ်၊ ကိုယ်ခန္ဓာဖွဲ့စည်းပုံ၊ ဝတ်ဆင်ထားသော အဝတ်အစား စသည်)\n"
            "5. တွေ့ရှိခဲ့သည့်နေရာ\n"
            "6. လက်ရှိတည်နေရာ/အခြေအနေ\n"
            "7. ဒဏ်ရာရရှိမှု သို့မဟုတ် ဆေးဝါးလိုအပ်ချက်များ\n"
            "8. သင့်ဆက်သွယ်ရန်အချက်အလက်\n\n"
            "*ဥပမာ:*\n"
            "1. အမည်မသိ၊ သူမအမည် မဟာ ဖြစ်နိုင်သည်ဟု ပြောပါသည်\n"
            "2. အသက် ၂၅-၃၀ ခန့်\n"
            "3. မ\n"
            "4. အလယ်အလတ်အရပ်၊ ပိန်ပိန်သွယ်သွယ်၊ ဆံပင်ရှည် အမည်း၊ အကျႌဖြူနှင့် ထဘီ အပြာ ဝတ်ဆင်ထား\n"
            "5. အဆောက်အဦးမှ စစ်ဆေးရေး ချိန်တွင် ရူဘီမတ် အနီးတွင် တွေ့ရှိခဲ့\n"
            "6. လက်ရှိတွင် ရန်ကုန်အထွေထွေဆေးရုံကြီး၊ အရေးပေါ်ဌာနတွင် ရှိပါသည်\n"
            "7. လက်မောင်းတွင် အနည်းငယ် ဒဏ်ရာရထားပြီး သတိလစ်သလို ဖြစ်နေပါသည်\n"
            "8. ဆက်သွယ်ရန် - ဒေါက်တာသန့်၊ ရန်ကုန်အထွေထွေဆေးရုံကြီး - ၀၉၉၈၇၆၅၄၃၂၁\n\n"
            "*မှတ်ချက်:* နောက်အဆင့်တွင် ဓာတ်ပုံထည့်သွင်းနိုင်ပါသည်။"
        ),
        "Request Rescue": (
            "*ကယ်ဆယ်ရေးတောင်းဆိုချက်*\n\n"
            "ကျေးဇူးပြု၍ အောက်ပါအချက်အလက်များကို တစ်ခုတည်းသော စာတစ်စောင်တွင် ပေးပို့ပါ -\n\n"
            "1. တိကျသော တည်နေရာ (တတ်နိုင်သမျှ အသေးစိတ်ဖော်ပြပါ)\n"
            "2. ကယ်ဆယ်ရန် လိုအပ်သူ အရေအတွက်\n"
            "3. ဒဏ်ရာရရှိမှု သို့မဟုတ် ဆေးဝါးလိုအပ်ချက်များ\n"
            "4. လက်ရှိအခြေအနေ (ပိတ်မိနေခြင်း၊ မလုံခြုံသော အဆောက်အအုံ စသည်)\n"
            "5. သင့်ဆက်သွယ်ရန်အချက်အလက်\n\n"
            "*ဥပမာ:*\n"
            "1. အမှတ် ၁၂၃၊ ဗိုလ်ချုပ်လမ်း၊ ကျောက်တံတားမြို့နယ်၊ ရန်ကုန်။ သုံးထပ်တိုက် အဖြူရောင် အိမ်၊ တံခါးအပြာရောင်၊ ဒုတိယထပ် တိုက်ခန်းတွင် ပိတ်မိနေပါသည်\n"
            "2. ၄ ဦး (လူကြီး ၂ ဦး၊ ကလေး ၂ ဦး အသက် ၇ နှစ်နှင့် ၃ နှစ်)\n"
            "3. အသက်ကြီးသော အမျိုးသမီးတစ်ဦးမှာ နှလုံးရောဂါရှိ၍ ဆေးလိုအပ်ပါသည်၊ အခြားသူများမှာ ဒဏ်ရာမရှိပါ\n"
            "4. အဆောက်အအုံ တစ်စိတ်တစ်ပိုင်း ပြိုကျထား၊ လှေကားကို အပျက်အစီးများက ပိတ်ဆို့နေ၊ ကျွန်ုပ်တို့သည် အရှေ့မြောက်ဘက်ထောင့်ခန်းတွင် ရှိနေပါသည်\n"
            "5. ဆက်သွယ်ရန် - ကိုအောင် - ၀၉၅၅၅၁၂၃၄၅၆ (ဖုန်းလိုင်းအားနည်းသော်လည်း SMS အလုပ်လုပ်ပါသည်)\n\n"
            "*မှတ်ချက်:* နောက်အဆင့်တွင် ဓာတ်ပုံထည့်သွင်းနိုင်ပါသည်။"
        ),
        "Offer Help": (
            "*အကူအညီပေးရန် ကမ်းလှမ်းမှု*\n\n"
            "ကျေးဇူးပြု၍ အောက်ပါအချက်အလက်များကို တစ်ခုတည်းသော စာတစ်စောင်တွင် ပေးပို့ပါ -\n\n"
            "1. ပေးဆောင်နိုင်သည့် အကူအညီအမျိုးအစား (ကယ်ဆယ်ရေး၊ ဆေးဝါး၊ ပစ္စည်းများ စသည်)\n"
            "2. သင့်တည်နေရာ\n"
            "3. ရရှိနိုင်သော အရင်းအမြစ်များ (ယာဉ်များ၊ ပစ္စည်းကိရိယာများ စသည်)\n"
            "4. သင့်ဆက်သွယ်ရန်အချက်အလက်\n\n"
            "*ဥပမာ:*\n"
            "1. ဆေးဝါးအကူအညီနှင့် ရှေးဦးသူနာပြုစုခြင်း၊ အသေးစား ဒဏ်ရာများနှင့် အခြေခံအရေးပေါ်စောင့်ရှောက်မှုတွင် ကူညီနိုင်\n"
            "2. လက်ရှိတွင် ရွှေလမ်း၊ ဗဟန်းမြို့နယ်၊ ရန်ကုန်တွင် ရှိပါသည်\n"
            "3. ဆေးဝါးပစ္စည်းများ၊ ရှေးဦးသူနာပြုစုခြင်းပစ္စည်းများ ရှိပြီး ဆိုင်ကယ်ဖြင့် ဒေသများသို့ သွားလာနိုင်ပါသည်\n"
            "4. ဆက်သွယ်ရန် - ဒေါက်တာဝင်းမြင့် - ၀၉၁၂၃၇၈၉၄၅၆၊ ၂၄ နာရီ အဆင်သင့်ရှိပါသည်\n\n"
            "*မှတ်ချက်:* နောက်အဆင့်တွင် ဓာတ်ပုံထည့်သွင်းနိုင်ပါသည်။"
        )
    }
    
    return instructions.get(report_type, "ကျေးဇူးပြု၍ ဆက်စပ်သော အချက်အလက်အားလုံးကို စာတစ်စောင်တည်းတွင် ပေးပို့ပါ။")

def determine_urgency(text: str) -> str:
    """Determine urgency level based on text content. Used as fallback."""
    text = text.lower()
    if "critical" in text or "emergency" in text or "urgent" in text or "life threatening" in text:
        return "Critical (Medical Emergency)"
    elif "high" in text or "trapped" in text or "injured" in text:
        return "High (Trapped/Missing)"
    elif "medium" in text or "safe" in text:
        return "Medium (Safe but Separated)"
    return "Low (Information Only)"

def format_report_message(user_data: dict, report_id: str, priority_icon: str, timestamp: str, user) -> str:
    """Format the report message for Telegram channels using HTML instead of Markdown."""
    location_info = ""
    if user_data.get('location'):
        location_info = f"📍 <b>LOCATION / တည်နေရာ:</b>\n<code>{user_data['location']}</code>\n\n"

    report_type_header = f"{priority_icon} <b>{user_data['report_type'].upper()}</b> {priority_icon}"
    
    # Use user_data instead of report for urgency
    urgency_level = user_data.get('urgency', 'N/A')
    urgency_emoji = "🔴" if "Critical" in urgency_level else "🟠" if "High" in urgency_level else "🟡" if "Medium" in urgency_level else "🟢"
    
    # Format the details with better spacing
    details = user_data['all_data'].strip()

    # Add photo URL info if available
    photo_info = ""
    if user_data.get('photo_url'):
        photo_info = f"📷 <b>PHOTO / ဓာတ်ပုံ:</b> <a href='{user_data['photo_url']}'>View Photo</a>\n\n"

    return (
        f"{report_type_header}\n"
        f"\n\n"
        f"🆔 <b>REPORT ID / အစီရင်ခံအမှတ်:</b>\n<code>{report_id}</code>\n\n"
        f"{location_info}"
        f"ℹ️ <b>DETAILS / အသေးစိတ်:</b>\n<code>{details}</code>\n\n"  # Changed <p> to <code>
        f"{photo_info}"
        f"{urgency_emoji} <b>URGENCY / အရေးပေါ်အဆင့်:</b>\n<code>{urgency_level}</code>\n\n"
        f"⏰ <b>REPORTED / အချိန်:</b>\n<code>{timestamp} (Asia/Yangon)</code>\n\n"
        f"👤 <b>REPORTED BY / တင်သွင်းသူ:</b>\n<code>{user.first_name} {user.last_name or ''}</code>\n\n"
    )

def store_report(report_id: str, user_data: dict, user, timestamp: str) -> None:
    """Store report in memory."""
    REPORTS[report_id] = {
        'report_type': user_data['report_type'],
        'all_data': user_data['all_data'],
        'urgency': user_data['urgency'],
        'timestamp': timestamp,
        'photo_id': user_data.get('photo_id'),
        'photo_url': user_data.get('photo_url'),
        'photo_path': user_data.get('photo_path'),
        'user_id': user.id,
        'username': user.username,
        'location': user_data.get('location', 'Unknown'),
        'status': user_data.get('status', 'Still Missing')  # Add status field with default
    }

async def send_report_to_channel(bot, user_data: dict, safe_message: str) -> None:
    """Send report to the channel."""
    if not CHANNEL_ID:
        logger.warning("No channel ID configured. Report not sent to channel.")
        return
    
    try:
        if user_data.get('photo_id'):
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=user_data['photo_id'],
                caption=safe_message,
                parse_mode=ParseMode.HTML
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=safe_message,
                parse_mode=ParseMode.HTML
            )
        logger.info(f"Report sent to channel {CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Failed to send report to channel: {str(e)}")

def get_s3_client():
    """Get configured S3 client for DigitalOcean Spaces"""
    try:
        # Get credentials from environment variables
        endpoint_url = os.environ.get('DO_SPACES_ENDPOINT')
        region_name = os.environ.get('DO_SPACES_REGION', 'sgp1')
        access_key = os.environ.get('DO_SPACES_KEY')
        secret_key = os.environ.get('DO_SPACES_SECRET')
        
        # Debug log the configuration (without secrets)
        logger.info(f"Connecting to Digital Ocean Spaces at {endpoint_url} in region {region_name}")
        
        if not endpoint_url:
            logger.error("Missing DO_SPACES_ENDPOINT environment variable")
            return None
            
        if not access_key or not secret_key:
            logger.error("Missing Digital Ocean Spaces credentials in environment variables")
            return None
        
        # Create and return the S3 client - IMPORTANT: use correct signature version for DO Spaces
        s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4')  # Use s3v4 instead of s3
        )
        
        # Test connection with a simple operation
        try:
            # Instead of list_buckets, try a more specific operation for the bucket
            bucket_name = os.environ.get('DO_SPACES_BUCKET', 'photos')
            logger.info(f"Testing connection to bucket: {bucket_name}")
            
            try:
                # First try to check if the bucket exists
                s3_client.head_bucket(Bucket=bucket_name)
                logger.info(f"Successfully connected to Digital Ocean Spaces bucket: {bucket_name}")
            except Exception as bucket_error:
                # If the bucket doesn't exist, try to create it
                logger.warning(f"Bucket check failed: {str(bucket_error)}")
                logger.info(f"Attempting to create bucket: {bucket_name}")
                location = {'LocationConstraint': region_name}
                s3_client.create_bucket(
                    Bucket=bucket_name,
                    ACL='public-read',
                    CreateBucketConfiguration=location
                )
                logger.info(f"Created bucket: {bucket_name}")
            
            return s3_client
        except Exception as conn_error:
            logger.error(f"Connection test to Digital Ocean Spaces failed: {str(conn_error)}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating S3 client: {str(e)}")
        return None

async def update_report_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle update report status request."""
    report_id = update.message.text.strip().upper()
    
    try:
        logger.info(f"Looking for report with ID: {report_id} to update status")
        
        # Get report from database
        report = await get_report(report_id)
        
        if not report:
            # Check in-memory backup
            if report_id in REPORTS:
                report = REPORTS[report_id]
            else:
                logger.info(f"No report found with ID: {report_id}")
                await update.message.reply_text(
                    "❌ No report found with that ID. Please check and try again.\n\n"
                    "ထို ID ဖြင့် အစီရင်ခံစာ မတွေ့ရှိပါ။ စစ်ဆေးပြီး ထပ်စမ်းကြည့်ပါ။"
                )
                return ConversationHandler.END
        
        # Get the owner's user ID 
        owner_id = report.get('user_id')
        
        # Check if user is the report owner
        if owner_id != update.effective_user.id:
            logger.warning(f"User {update.effective_user.id} attempted to update report {report_id} owned by user {owner_id}")
            
            # Get your Telegram ID for comparison
            your_id = update.effective_user.id
            
            await update.message.reply_text(
                f"❌ You can only update reports that you submitted.\n\n"
                f"This report (ID: {report_id}) belongs to user with ID: {owner_id}\n"
                f"Your user ID is: {your_id}\n\n"
                f"သင်တင်သွင်းခဲ့သော အစီရင်ခံစာများကိုသာ ပြင်ဆင်နိုင်ပါသည်။\n"
                f"ဤအစီရင်ခံစာသည် အသုံးပြုသူ ID: {owner_id} ၏ ပိုင်ဆိုင်မှုဖြစ်သည်။"
            )
            return ConversationHandler.END
        
        # Store report for later use
        context.user_data['updating_report'] = report
        context.user_data['updating_report_id'] = report_id
        
        # Get current status, defaulting to "Still Missing" if not set
        current_status = report.get('status')
        if not current_status or current_status == 'No status set':
            current_status = "Still Missing"
            # Update the report object to include this default
            report['status'] = current_status
        
        # Create keyboard with status options
        keyboard = [
            ["ပျောက်ဆုံးဆဲ (Still Missing)"],
            ["တွေ့ရှိပြီ (Found)"],
            ["ဆေးရုံရောက်ရှိနေ (Hospitalized)"],
            ["ကျဆုံးသွားပြီ (Deceased)"],
            ["အခြား (Other)"]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard, 
            one_time_keyboard=True, 
            resize_keyboard=True
        )

        await update.message.reply_text(
            f"လက်ရှိအခြေအနေ: *{current_status}*\n\n"
            f"အစီရင်ခံစာ {report_id} အတွက် အခြေအနေအသစ်ကို ရွေးချယ်ပါ:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
        return CHOOSE_STATUS
        
    except Exception as e:
        logger.error(f"Error in update_report_status: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "❌ An error occurred while retrieving the report. Please try again later."
        )
        return ConversationHandler.END

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle selection of new status."""
    status_text = update.message.text.strip()
    report_id = context.user_data.get('updating_report_id')
    
    if not report_id:
        await update.message.reply_text(
            "❌ Session expired. Please start again."
        )
        return ConversationHandler.END
    
    # Map Burmese status to database values
    status_map = {
        "ပျောက်ဆုံးဆဲ (Still Missing)": "Still Missing",
        "တွေ့ရှိပြီ (Found)": "Found",
        "ဆေးရုံရောက်ရှိနေ (Hospitalized)": "Hospitalized",
        "ကျဆုံးသွားပြီ (Deceased)": "Deceased",
        "အခြား (Other)": "Other"
    }
    
    # Use English status for database
    status = status_map.get(status_text, status_text)
    
    try:
        # Update status in database
        success = await update_report_status_in_db(report_id, status, update.effective_user.id)
        
        if success:
            # Remove keyboard and confirm update
            reply_markup = ReplyKeyboardRemove()
            
            await update.message.reply_text(
                f"✅ Status of report {report_id} has been updated to: *{status}*\n\n"
                f"အစီရင်ခံစာ {report_id} ၏ အခြေအနေကို *{status}* သို့ ပြောင်းလဲလိုက်ပါပြီ။",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
            # Return to main menu
            return await show_main_menu(update, context)
        else:
            await update.message.reply_text(
                "❌ Failed to update report status. Please try again later.\n\n"
                "အစီရင်ခံစာ အခြေအနေ ပြောင်းလဲခြင်း မအောင်မြင်ပါ။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error updating status: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "❌ An error occurred while updating the report status. Please try again later."
        )
        return ConversationHandler.END
