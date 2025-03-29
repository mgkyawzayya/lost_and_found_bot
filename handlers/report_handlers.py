from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
import uuid
import logging
import asyncio
from datetime import datetime
import pytz  # Import pytz for timezone handling

from utils.message_utils import escape_markdown_v2
from utils.db_utils import save_report, get_report_by_id, search_reports_by_content, search_missing_people, get_report
from config.constants import PRIORITIES, CHANNEL_ID
from config.states import (
    PHOTO, COLLECTING_DATA, SEARCHING_REPORT, DESCRIPTION, SEND_MESSAGE,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER, CHOOSING_LOCATION, CHOOSING_REPORT_TYPE,
    SELECT_URGENCY  # Make sure to add this to your states.py file
)
# Configure logger
logger = logging.getLogger(__name__)

# In-memory storage for reports if database is not available
REPORTS = {}

async def choose_report_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's selection of report type."""
    text = update.message.text
    context.user_data['report_type'] = text
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
            ['Yangon', 'Mandalay', 'Naypyidaw'],
            ['Bago', 'Sagaing', 'Magway'],
            ['Ayeyarwady', 'Tanintharyi', 'Mon'],
            ['Shan', 'Kachin', 'Kayah'],
            ['Kayin', 'Chin', 'Rakhine'],
            ['Other Location']
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
    
    # Continue with normal data collection flow
    if context.user_data['report_type'] == 'Missing Person (Earthquake)':
        await update.message.reply_text(
            "Please provide the following information about the missing person:\n"
            "1. Full Name\n"
            "2. Age\n"
            "3. Gender\n"
            "4. Last Known Location (be specific)\n"
            "5. Physical Description\n"
            "6. When Last Seen (date/time)\n"
            "7. Your Contact Information\n\n"
            "ပျောက်ဆုံးနေသူနှင့် ပတ်သက်သည့် အချက်အလက်များကို ဖြည့်စွက်ပေးပါ။"
        )
    elif context.user_data['report_type'] == 'Request Rescue':
        await update.message.reply_text(
            "Please provide the following rescue information:\n"
            "1. Number of people trapped\n"
            "2. Exact address/location\n"
            "3. Building condition\n"
            "4. Any injuries?\n"
            "5. Urgent needs (medical, water, etc.)\n"
            "6. Your name and relation to trapped\n"
            "7. Alternative contact method\n\n"
            "ကယ်ဆယ်ရေးအတွက် သတင်းအချက်အလက်များ ဖြည့်စွက်ပေးပါ။"
        )
    
    return COLLECTING_DATA

async def collect_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store all provided data at once and ask for urgency level."""
    context.user_data['all_data'] = update.message.text
    
    # Generate a unique report ID with location prefix if available
    prefix = context.user_data.get('case_prefix', '')
    if prefix:
        report_id = f"{prefix}-{str(uuid.uuid4())[:6].upper()}"
    else:
        report_id = str(uuid.uuid4())[:8].upper()
        
    context.user_data['report_id'] = report_id
    
    # Create urgency selection keyboard
    keyboard = [
        ["Critical (Medical Emergency)"],
        ["High (Trapped/Missing)"],
        ["Medium (Safe but Separated)"],
        ["Low (Information Only)"]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=True, 
        resize_keyboard=True
    )
    
    await update.message.reply_text(
        f"Thank you for providing this information. Your report ID is: *{report_id}*\n\n"
        "Please select the urgency level of your report:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return SELECT_URGENCY

async def select_urgency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the selection of urgency level."""
    selected_urgency = update.message.text
    
    # Store the selected urgency
    context.user_data['urgency'] = selected_urgency
    
    # Create a keyboard with a skip button for photo
    keyboard = [[
        "Skip Photo"
    ]]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=True, 
        resize_keyboard=True
    )
    
    await update.message.reply_text(
        "Urgency level set. Thank you.\n\n"
        "📸 If you have a photo, please send it now.\n"
        "Or click 'Skip Photo' to continue without a photo.\n\n"
        "ဓာတ်ပုံရှိပါက ယခုပေးပို့နိုင်ပါသည်။\n"
        "မရှိပါက 'Skip Photo' ခလုတ်ကိုနှိပ်ပါ။",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return PHOTO

async def finalize_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finalize and save the report to the database"""
    try:
        user_data = context.user_data
        
        # Prepare report data
        report_data = {
            'report_id': user_data.get('report_id', ''),
            'report_type': user_data.get('report_type', ''),
            'all_data': user_data.get('all_data', ''),
            'urgency': user_data.get('urgency', ''),
            'photo': user_data.get('photo_id', None),
            'location': user_data.get('location', 'Unknown')  # Ensure location is included
        }
        
        # Get telegram user object
        telegram_user = update.effective_user
        
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
                    safe_message = escape_markdown_v2(
                        format_report_message(user_data, report_data['report_id'], priority_icon, timestamp, telegram_user)
                    )
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
                safe_message = escape_markdown_v2(
                    format_report_message(user_data, report_id, priority_icon, timestamp, telegram_user)
                )
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
            logger.error(f"Error saving report: {str(e)}")
            await update.message.reply_text(
                "❌ Error saving your report. Please try again later.\n\n"
                "သင့်အစီရင်ခံစာကို မသိမ်းဆည်းနိုင်ပါ။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error in finalize_report: {str(e)}")
        await update.message.reply_text(
            "❌ An unexpected error occurred. Please try again later.\n\n"
            "မမျှော်လင့်ထားသော အမှားတစ်ခု ဖြစ်ပေါ်ခဲ့သည်။ နောက်မှ ထပ်စမ်းကြည့်ပါ။"
        )
        return ConversationHandler.END        

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the photo and finalize the report."""
    try:
        # Check if we received a photo
        if update.message.photo:
            # Get the largest available photo (best quality)
            photo_file = update.message.photo[-1].file_id
            context.user_data['photo_id'] = photo_file
            
            # Log success
            logger.info(f"Photo received for report ID: {context.user_data.get('report_id')}")
            
            # Remove keyboard
            reply_markup = ReplyKeyboardRemove()
            
            # Acknowledge photo receipt
            await update.message.reply_text(
                "✅ Photo received! Processing your report...",
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
        logger.error(f"Error processing photo: {str(e)}")
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
        
        # Allow either "skip" (typed) or "Skip Photo" (button press)
        if user_input.lower() == "skip" or user_input == "Skip Photo":
            # Set no photo indicator
            context.user_data['photo_id'] = None
            
            # Remove keyboard
            reply_markup = ReplyKeyboardRemove()
            await update.message.reply_text(
                "Skipping photo upload...",
                reply_markup=reply_markup
            )
            
            # Return to main flow
            return await finalize_report(update, context)
        else:
            # User input something else - ask again
            keyboard = [[
                "Skip Photo"
            ]]
            reply_markup = ReplyKeyboardMarkup(
                keyboard, 
                one_time_keyboard=True, 
                resize_keyboard=True
            )
            
            await update.message.reply_text(
                "Please either send a photo or click 'Skip Photo'.\n\n"
                "ဓာတ်ပုံပေးပို့ပါ သို့မဟုတ် 'Skip Photo' ကိုနှိပ်ပါ။",
                reply_markup=reply_markup
            )
            
            # Stay in the same state
            return PHOTO
    except Exception as e:
        logger.error(f"Error in handle_skip_photo: {str(e)}")
        await update.message.reply_text(
            "❌ An error occurred. Please try again or /cancel to start over."
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
                memory_report = REPORTS[report_id]
                logger.info(f"Found report {report_id} in memory storage")
                
                # Format the time correctly for memory reports
                report_time = memory_report.get('timestamp', 'N/A')
                if report_time != 'N/A' and 'T' in report_time:  # ISO format has 'T' separator
                    try:
                        # Parse ISO format timestamp
                        dt = datetime.fromisoformat(report_time)
                        # If timezone info not in timestamp, assume it's already in Myanmar timezone
                        if dt.tzinfo is None:
                            myanmar_tz = pytz.timezone('Asia/Yangon')
                            dt = myanmar_tz.localize(dt)
                        report_time = dt.strftime("%Y-%m-%d %H:%M:%S") + " (Asia/Yangon)"
                    except Exception as e:
                        logger.error(f"Error formatting timestamp: {str(e)}")
                
                await update.message.reply_text(
                    f"📋 *Report Found in Temporary Storage:*\n\n"
                    f"📝 *Type:* {memory_report.get('report_type', 'N/A')}\n\n"
                    f"ℹ️ *Details:*\n{memory_report.get('all_data', 'N/A')}\n\n"
                    f"🟠 *Urgency:* {memory_report.get('urgency', 'N/A')}\n\n"
                    f"⏰ *Submitted:* {report_time}\n\n"
                    f"⚠️ This report is stored temporarily and will be transferred to the database soon.",
                    parse_mode='MARKDOWN'
                )
                
                # If there's a photo, send it too
                if memory_report.get('photo'):
                    await update.message.reply_photo(memory_report['photo'])
                    
                return CHOOSING_REPORT_TYPE
            
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
                # Check if created_at is a string or datetime
                if isinstance(created_at, str):
                    # Try to parse the string to a datetime object
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00')) if 'Z' in created_at else datetime.fromisoformat(created_at)
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
        
        response += f"⏰ *Submitted:* {created_at}\n"
        
        await update.message.reply_text(response, parse_mode='MARKDOWN')
        
        # If there's a photo, send it too
        photo_id = report.get('photo_id')
        if photo_id:
            try:
                await update.message.reply_photo(photo_id)
            except Exception as photo_error:
                logger.error(f"Error sending photo: {str(photo_error)}")
                await update.message.reply_text(
                    "⚠️ Could not display the photo associated with this report."
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
        ['Missing Person (Earthquake)', 'Found Person (Earthquake)'],
        ['Request Rescue', 'Offer Help'],
        ['Search Reports by ID', 'Contact Report Submitter'],
        ['Search for Missing Person']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "What would you like to do next?",
        reply_markup=reply_markup
    )
    
    # Return to CHOOSING_REPORT_TYPE state to handle the next menu selection
    return CHOOSING_REPORT_TYPE

# Helper functions
def get_instructions_by_type(report_type):
    """Return instructions based on report type."""
    instructions = {
        "Missing Person (Earthquake)": (
            "*Missing Person Report*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Person's name\n"
            "2. Age\n"
            "3. Gender\n"
            "4. Physical description (height, build, clothing, etc.)\n"
            "5. Last known location (be as specific as possible)\n"
            "6. When they were last seen (date/time)\n"
            "7. Any medical conditions or special needs\n"
            "8. Your contact information\n\n"
            "*Example:*\n"
            "1. Aung Ko\n"
            "2. 35\n"
            "3. Male\n" 
            "4. Tall (5'10\"), thin build, black hair, was wearing blue jeans and red t-shirt\n"
            "5. Last seen at Sule Square Mall, 2nd floor near the food court\n"
            "6. November 26, 2023 around 2:30pm\n"
            "7. Diabetes, needs regular medication\n"
            "8. Contact: Thu Thu (sister) - 09123456789\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Found Person (Earthquake)": (
            "*Found Person Report*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Person's name (if known)\n"
            "2. Approximate age\n"
            "3. Gender\n"
            "4. Physical description (height, build, clothing, etc.)\n"
            "5. Where they were found\n"
            "6. Current location/status\n"
            "7. Any injuries or medical needs\n"
            "8. Your contact information\n\n"
            "*Example:*\n"
            "1. Unknown name, says her name may be Ma Hla\n"
            "2. About 25-30 years old\n"
            "3. Female\n"
            "4. Medium height, slim, long black hair, wearing white blouse and blue longyi\n"
            "5. Found near Ruby Mart after building evacuation\n"
            "6. Currently at Yangon General Hospital, Emergency Ward\n"
            "7. Minor cuts on arms, seems disoriented\n"
            "8. Contact: Dr. Thant, Yangon General Hospital - 09987654321\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Request Rescue": (
            "*Rescue Request*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Exact location (be as specific as possible)\n"
            "2. Number of people needing rescue\n"
            "3. Any injuries or medical needs\n"
            "4. Current situation (trapped, unsafe building, etc.)\n"
            "5. Your contact information\n\n"
            "*Example:*\n"
            "1. No. 123, Bogyoke Street, Kyauktada Township, Yangon. Three-story white building with blue gate, trapped on 2nd floor apartment\n"
            "2. 4 people (2 adults, 2 children ages 7 and 3)\n"
            "3. Elderly woman with heart condition needs medication, others appear uninjured\n"
            "4. Building partially collapsed, stairway blocked by debris, we are in the northeast corner room\n"
            "5. Contact: Ko Aung - 09555123456 (weak signal but SMS works)\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Offer Help": (
            "*Help Offer*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Type of help you can provide (rescue, medical, supplies, etc.)\n"
            "2. Your location\n"
            "3. Resources available (vehicles, equipment, etc.)\n"
            "4. Your contact information\n\n"
            "*Example:*\n"
            "1. Medical assistance and first aid, can help with minor injuries and basic emergency care\n"
            "2. Currently at Golden Valley, Bahan Township, Yangon\n"
            "3. Have medical supplies, first aid kits, can travel by motorcycle to affected areas\n"
            "4. Contact: Dr. Win Myint - 09123789456, available 24 hours\n\n"
            "*Note:* You can add a photo in the next step."
        )
    }
    
    return instructions.get(report_type, "Please provide all relevant information in a single message.")

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
    """Format the report message with improved readability and emphasis."""
    # Get location info if available
    location_info = ""
    if user_data.get('location'):
        location_info = f"📍 *LOCATION / တည်နေရာ:*\n{user_data['location']}\n\n"
    
    # Format report type with larger text indicators
    report_type_header = f"{priority_icon} *{user_data['report_type'].upper()}* {priority_icon}"
    
    # Format urgency level with appropriate emoji
    urgency_level = user_data['urgency']
    urgency_emoji = "🔴" if "Critical" in urgency_level else "🟠" if "High" in urgency_level else "🟡" if "Medium" in urgency_level else "🟢"
    
    # Create sections with clear visual separation
    return (
        f"{report_type_header}\n\n"
        f"🆔 *REPORT ID / အစီရင်ခံအမှတ်:*\n`{report_id}`\n\n"
        f"{location_info}"
        f"ℹ️ *DETAILS / အသေးစိတ်:*\n{user_data['all_data']}\n\n"
        f"{urgency_emoji} *URGENCY / အရေးပေါ်အဆင့်:*\n{urgency_level}\n\n"
        f"⏰ *REPORTED / အချိန်:*\n{timestamp} (Asia/Yangon)\n\n"  # Added timezone indicator
        f"👤 *REPORTED BY / တင်သွင်းသူ:*\n{user.first_name} {user.last_name or ''}"
    )

def store_report(report_id: str, user_data: dict, user, timestamp: str) -> None:
    """Store report in memory."""
    REPORTS[report_id] = {
        'report_type': user_data['report_type'],
        'all_data': user_data['all_data'],
        'urgency': user_data['urgency'],
        'timestamp': timestamp,
        'photo': user_data.get('photo_id'),
        'user_id': user.id,
        'username': user.username,
        'location': user_data.get('location', 'Unknown')
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
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=safe_message,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        logger.info(f"Report sent to channel {CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Failed to send report to channel: {str(e)}")

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
                memory_report = REPORTS[report_id]
                logger.info(f"Found report {report_id} in memory storage")
                
                # Format the time correctly for memory reports
                report_time = memory_report.get('timestamp', 'N/A')
                if report_time != 'N/A' and 'T' in report_time:  # ISO format has 'T' separator
                    try:
                        # Parse ISO format timestamp
                        dt = datetime.fromisoformat(report_time)
                        # If timezone info not in timestamp, assume it's already in Myanmar timezone
                        if dt.tzinfo is None:
                            myanmar_tz = pytz.timezone('Asia/Yangon')
                            dt = myanmar_tz.localize(dt)
                        report_time = dt.strftime("%Y-%m-%d %H:%M:%S") + " (Asia/Yangon)"
                    except Exception as e:
                        logger.error(f"Error formatting timestamp: {str(e)}")
                
                await update.message.reply_text(
                    f"📋 *Report Found in Temporary Storage:*\n\n"
                    f"📝 *Type:* {memory_report.get('report_type', 'N/A')}\n\n"
                    f"ℹ️ *Details:*\n{memory_report.get('all_data', 'N/A')}\n\n"
                    f"🟠 *Urgency:* {memory_report.get('urgency', 'N/A')}\n\n"
                    f"⏰ *Submitted:* {report_time}\n\n"
                    f"⚠️ This report is stored temporarily and will be transferred to the database soon.",
                    parse_mode='MARKDOWN'
                )
                
                # If there's a photo, send it too
                if memory_report.get('photo'):
                    await update.message.reply_photo(memory_report['photo'])
                    
                return CHOOSING_REPORT_TYPE
            
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
                # Check if created_at is a string or datetime
                if isinstance(created_at, str):
                    # Try to parse the string to a datetime object
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00')) if 'Z' in created_at else datetime.fromisoformat(created_at)
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
        
        response += f"⏰ *Submitted:* {created_at}\n"
        
        await update.message.reply_text(response, parse_mode='MARKDOWN')
        
        # If there's a photo, send it too
        photo_id = report.get('photo_id')
        if photo_id:
            try:
                await update.message.reply_photo(photo_id)
            except Exception as photo_error:
                logger.error(f"Error sending photo: {str(photo_error)}")
                await update.message.reply_text(
                    "⚠️ Could not display the photo associated with this report."
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
        ['Missing Person (Earthquake)', 'Found Person (Earthquake)'],
        ['Request Rescue', 'Offer Help'],
        ['Search Reports by ID', 'Contact Report Submitter'],
        ['Search for Missing Person']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "What would you like to do next?",
        reply_markup=reply_markup
    )
    
    # Return to CHOOSING_REPORT_TYPE state to handle the next menu selection
    return CHOOSING_REPORT_TYPE

# Helper functions
def get_instructions_by_type(report_type):
    """Return instructions based on report type."""
    instructions = {
        "Missing Person (Earthquake)": (
            "*Missing Person Report*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Person's name\n"
            "2. Age\n"
            "3. Gender\n"
            "4. Physical description (height, build, clothing, etc.)\n"
            "5. Last known location (be as specific as possible)\n"
            "6. When they were last seen (date/time)\n"
            "7. Any medical conditions or special needs\n"
            "8. Your contact information\n\n"
            "*Example:*\n"
            "1. Aung Ko\n"
            "2. 35\n"
            "3. Male\n" 
            "4. Tall (5'10\"), thin build, black hair, was wearing blue jeans and red t-shirt\n"
            "5. Last seen at Sule Square Mall, 2nd floor near the food court\n"
            "6. November 26, 2023 around 2:30pm\n"
            "7. Diabetes, needs regular medication\n"
            "8. Contact: Thu Thu (sister) - 09123456789\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Found Person (Earthquake)": (
            "*Found Person Report*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Person's name (if known)\n"
            "2. Approximate age\n"
            "3. Gender\n"
            "4. Physical description (height, build, clothing, etc.)\n"
            "5. Where they were found\n"
            "6. Current location/status\n"
            "7. Any injuries or medical needs\n"
            "8. Your contact information\n\n"
            "*Example:*\n"
            "1. Unknown name, says her name may be Ma Hla\n"
            "2. About 25-30 years old\n"
            "3. Female\n"
            "4. Medium height, slim, long black hair, wearing white blouse and blue longyi\n"
            "5. Found near Ruby Mart after building evacuation\n"
            "6. Currently at Yangon General Hospital, Emergency Ward\n"
            "7. Minor cuts on arms, seems disoriented\n"
            "8. Contact: Dr. Thant, Yangon General Hospital - 09987654321\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Request Rescue": (
            "*Rescue Request*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Exact location (be as specific as possible)\n"
            "2. Number of people needing rescue\n"
            "3. Any injuries or medical needs\n"
            "4. Current situation (trapped, unsafe building, etc.)\n"
            "5. Your contact information\n\n"
            "*Example:*\n"
            "1. No. 123, Bogyoke Street, Kyauktada Township, Yangon. Three-story white building with blue gate, trapped on 2nd floor apartment\n"
            "2. 4 people (2 adults, 2 children ages 7 and 3)\n"
            "3. Elderly woman with heart condition needs medication, others appear uninjured\n"
            "4. Building partially collapsed, stairway blocked by debris, we are in the northeast corner room\n"
            "5. Contact: Ko Aung - 09555123456 (weak signal but SMS works)\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Offer Help": (
            "*Help Offer*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Type of help you can provide (rescue, medical, supplies, etc.)\n"
            "2. Your location\n"
            "3. Resources available (vehicles, equipment, etc.)\n"
            "4. Your contact information\n\n"
            "*Example:*\n"
            "1. Medical assistance and first aid, can help with minor injuries and basic emergency care\n"
            "2. Currently at Golden Valley, Bahan Township, Yangon\n"
            "3. Have medical supplies, first aid kits, can travel by motorcycle to affected areas\n"
            "4. Contact: Dr. Win Myint - 09123789456, available 24 hours\n\n"
            "*Note:* You can add a photo in the next step."
        )
    }
    
    return instructions.get(report_type, "Please provide all relevant information in a single message.")

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
    """Format the report message with improved readability and emphasis."""
    # Get location info if available
    location_info = ""
    if user_data.get('location'):
        location_info = f"📍 *LOCATION / တည်နေရာ:*\n{user_data['location']}\n\n"
    
    # Format report type with larger text indicators
    report_type_header = f"{priority_icon} *{user_data['report_type'].upper()}* {priority_icon}"
    
    # Format urgency level with appropriate emoji
    urgency_level = user_data['urgency']
    urgency_emoji = "🔴" if "Critical" in urgency_level else "🟠" if "High" in urgency_level else "🟡" if "Medium" in urgency_level else "🟢"
    
    # Create sections with clear visual separation
    return (
        f"{report_type_header}\n\n"
        f"🆔 *REPORT ID / အစီရင်ခံအမှတ်:*\n`{report_id}`\n\n"
        f"{location_info}"
        f"ℹ️ *DETAILS / အသေးစိတ်:*\n{user_data['all_data']}\n\n"
        f"{urgency_emoji} *URGENCY / အရေးပေါ်အဆင့်:*\n{urgency_level}\n\n"
        f"⏰ *REPORTED / အချိန်:*\n{timestamp} (Asia/Yangon)\n\n"  # Added timezone indicator
        f"👤 *REPORTED BY / တင်သွင်းသူ:*\n{user.first_name} {user.last_name or ''}"
    )

def store_report(report_id: str, user_data: dict, user, timestamp: str) -> None:
    """Store report in memory."""
    REPORTS[report_id] = {
        'report_type': user_data['report_type'],
        'all_data': user_data['all_data'],
        'urgency': user_data['urgency'],
        'timestamp': timestamp,
        'photo': user_data.get('photo_id'),
        'user_id': user.id,
        'username': user.username,
        'location': user_data.get('location', 'Unknown')
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
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=safe_message,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        logger.info(f"Report sent to channel {CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Failed to send report to channel: {str(e)}")
