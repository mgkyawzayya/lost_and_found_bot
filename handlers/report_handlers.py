from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
import uuid
import logging
from datetime import datetime

from utils.message_utils import escape_markdown_v2
from utils.db_utils import save_report, get_report_by_id, search_reports_by_content
from config.constants import PRIORITIES, CHANNEL_ID
from config.states import (
    PHOTO, COLLECTING_DATA, SEARCHING_REPORT, DESCRIPTION, SEND_MESSAGE,
    SEARCH_MISSING_PERSON, SEND_MESSAGE_TO_REPORTER
)
# Configure logger
logger = logging.getLogger(__name__)

# In-memory storage for reports if database is not available
REPORTS = {}

async def choose_report_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the report type and ask for all data at once."""
    try:
        user_choice = update.message.text.strip()  # Get the raw input
        logger.info(f"DEBUG: choose_report_type called with input: '{user_choice}'")
        
        # Define valid options with their canonical form
        valid_options = {
            "search reports by id": "Search Reports by ID",
            "contact report submitter": "Contact Report Submitter",
            "missing person (earthquake)": "Missing Person (Earthquake)",
            "found person (earthquake)": "Found Person (Earthquake)",
            "lost item": "Lost Item",
            "found item": "Found Item",
            "request rescue": "Request Rescue",
            "offer help": "Offer Help",
            "search for missing person": "Search for Missing Person"  # Add the new option
        }
        
        # Check for match ignoring case
        user_choice_lower = user_choice.lower()
        logger.info(f"DEBUG: user_choice_lower: '{user_choice_lower}'")
        
        # Check if the lower-cased input matches any key
        if user_choice_lower in valid_options:
            canonical_choice = valid_options[user_choice_lower]
            logger.info(f"DEBUG: Matched to canonical form: '{canonical_choice}'")
            
            if canonical_choice == "Search Reports by ID":
                await update.message.reply_text(
                    "Please enter the Report ID you want to search for:"
                )
                return SEARCHING_REPORT
                
            if canonical_choice == "Contact Report Submitter":
                await update.message.reply_text(
                    "Please enter the Report ID of the post whose submitter you want to contact:"
                )
                return SEND_MESSAGE
                
            if canonical_choice == "Search for Missing Person":
                await update.message.reply_text(
                    "Please enter the name or any details (like location, appearance) of the missing person:"
                )
                return SEARCH_MISSING_PERSON
            
            # Handle report types
            context.user_data['report_type'] = canonical_choice
            instructions = get_instructions_by_type(canonical_choice)
            
            logger.info(f"DEBUG: Providing instructions for: {canonical_choice}")
            
            await update.message.reply_text(
                instructions,
                parse_mode=ParseMode.MARKDOWN
            )
            return COLLECTING_DATA
        
        # Direct match with the canonical form
        for key, value in valid_options.items():
            if user_choice == value:
                logger.info(f"DEBUG: Direct match found: '{value}'")
                
                if value == "Search Reports by ID":
                    await update.message.reply_text(
                        "Please enter the Report ID you want to search for:"
                    )
                    return SEARCHING_REPORT
                    
                if value == "Contact Report Submitter":
                    await update.message.reply_text(
                        "Please enter the Report ID of the post whose submitter you want to contact:"
                    )
                    return SEND_MESSAGE
                    
                if value == "Search for Missing Person":
                    await update.message.reply_text(
                        "Please enter the name or any details (like location, appearance) of the missing person:"
                    )
                    return SEARCH_MISSING_PERSON
                
                # Handle report types
                context.user_data['report_type'] = value
                instructions = get_instructions_by_type(value)
                
                logger.info(f"DEBUG: Providing instructions for: {value}")
                
                await update.message.reply_text(
                    instructions,
                    parse_mode=ParseMode.MARKDOWN
                )
                return COLLECTING_DATA
        
        # If we got here, no match was found
        logger.warning(f"DEBUG: No match found for: '{user_choice}'")
        await update.message.reply_text(
            "Invalid selection. Please use /start to see available options and try again.\n\n"
            "Available options:\n" +
            "\n".join(f"- {value}" for value in valid_options.values())
        )
        
        # Return to the same state to let the user try again
        return CHOOSING_REPORT_TYPE
        
    except Exception as e:
        logger.error(f"ERROR in choose_report_type: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "An error occurred processing your selection. Please use /start to try again."
        )
        return ConversationHandler.END

async def collect_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store all provided data at once and ask for photo."""
    context.user_data['all_data'] = update.message.text
    
    # Assign urgency based on keywords
    context.user_data['urgency'] = determine_urgency(update.message.text)
    
    # Generate a unique report ID
    report_id = str(uuid.uuid4())[:8].upper()
    context.user_data['report_id'] = report_id
    
    # Create a keyboard with a skip button
    keyboard = [[
        "Skip Photo"
    ]]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=True, 
        resize_keyboard=True
    )
    
    await update.message.reply_text(
        f"Thank you for providing this information. Your report ID is: *{report_id}*\n\n"
        "📸 If you have a photo, please send it now.\n"
        "Or click 'Skip Photo' to continue without a photo.\n\n"
        "ဓာတ်ပုံရှိပါက ယခုပေးပို့နိုင်ပါသည်။\n"
        "မရှိပါက 'Skip Photo' ခလုတ်ကိုနှိပ်ပါ။",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return PHOTO

async def finalize_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Format and send the report to the channel."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    priority_icon = PRIORITIES.get(context.user_data.get('urgency', "Low (Information Only)"), "")
    report_id = context.user_data['report_id']

    raw_message = format_report_message(
        context.user_data, 
        report_id, 
        priority_icon, 
        timestamp, 
        update.effective_user
    )

    safe_message = escape_markdown_v2(raw_message)
    
    try:
        # Save report to database or in-memory if database fails
        try:
            save_report(context.user_data, update.effective_user)
        except Exception as db_error:
            logger.error(f"Database error: {str(db_error)}. Using in-memory storage instead.")
            store_report(report_id, context.user_data, update.effective_user, timestamp)
        
        # Send report to channel
        await send_report_to_channel(context.bot, context.user_data, safe_message)
        
        # Send confirmation to user
        await send_confirmation_to_user(update, context, report_id)
        
    except Exception as e:
        await handle_report_error(update, e)

    context.user_data.clear()
    return ConversationHandler.END

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the photo and finalize the report."""
    try:
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
    except Exception as e:
        logger.error(f"Error processing photo: {str(e)}")
        await update.message.reply_text(
            "❌ There was an error processing your photo. Please try again."
        )
        return PHOTO

async def handle_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle skipping the photo."""
    
    # Check if the user clicked the skip button or typed "skip"
    user_input = update.message.text.strip()
    
    logger.info(f"Photo skip handler received: {user_input}")
    
    # Allow either "skip" (typed) or "Skip Photo" (button press)
    if user_input.lower() == "skip" or user_input == "Skip Photo":
        # Set no photo indicator
        context.user_data['photo_id'] = None
        
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

async def search_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for a report by ID."""
    report_id = update.message.text.strip().upper()
    
    try:
        report = get_report_by_id(report_id)
        
        if report:
            await update.message.reply_text(
                f"📄 *Report Found*\n\n"
                f"*Report ID:* `{report.report_id}`\n"
                f"*Type:* {report.report_type}\n"
                f"*Urgency:* {report.urgency}\n"
                f"*Date:* {report.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"*Details:*\n{report.details}",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # If the report has a photo, send it
            if report.photo_file_id:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=report.photo_file_id
                )
        else:
            # Check in-memory storage if database failed
            if report_id in REPORTS:
                report_data = REPORTS[report_id]
                await update.message.reply_text(
                    f"📄 *Report Found (In-Memory)*\n\n"
                    f"*Report ID:* `{report_id}`\n"
                    f"*Type:* {report_data['report_type']}\n"
                    f"*Urgency:* {report_data['urgency']}\n"
                    f"*Date:* {report_data['timestamp']}\n\n"
                    f"*Details:*\n{report_data['all_data']}",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # If the report has a photo, send it
                if report_data.get('photo'):
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=report_data['photo']
                    )
            else:
                await update.message.reply_text(
                    f"❌ No report found with ID: {report_id}"
                )
    except Exception as e:
        logger.error(f"Error searching report: {str(e)}")
        await update.message.reply_text(
            f"❌ Error searching for report: {report_id}. Please try again later."
        )
    
    return ConversationHandler.END

async def send_message_to_submitter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a message to the submitter of a report."""
    if 'contact_report_id' not in context.user_data:
        report_id = update.message.text.strip().upper()
        
        try:
            report = get_report_by_id(report_id)
            
            if not report and report_id in REPORTS:
                # Use in-memory data if available
                user_id = REPORTS[report_id]['user_id']
                context.user_data['contact_report_id'] = report_id
                context.user_data['contact_user_id'] = user_id
                
                await update.message.reply_text(
                    f"✅ Report found! Please type your message to send to the submitter of report {report_id}:"
                )
                return DESCRIPTION
            
            if not report:
                await update.message.reply_text(
                    f"❌ No report found with ID: {report_id}"
                )
                return ConversationHandler.END
                
            user_id = report.user_id
            context.user_data['contact_report_id'] = report_id
            context.user_data['contact_user_id'] = user_id
            
            await update.message.reply_text(
                f"✅ Report found! Please type your message to send to the submitter of report {report_id}:"
            )
            return DESCRIPTION
            
        except Exception as e:
            logger.error(f"Error finding report submitter: {str(e)}")
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
            "6. When they were last seen (date and time)\n"
            "7. Any medical conditions or special needs\n"
            "8. Your contact information\n\n"
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
            "*Note:* You can add a photo in the next step."
        ),
        "Lost Item": (
            "*Lost Item Report*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Item description\n"
            "2. Where and when it was lost\n"
            "3. Any identifying features\n"
            "4. Your contact information\n\n"
            "*Note:* You can add a photo in the next step."
        ),
        "Found Item": (
            "*Found Item Report*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Item description\n"
            "2. Where and when it was found\n"
            "3. Where the item is now\n"
            "4. Your contact information\n\n"
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
            "*Note:* You can add a photo in the next step."
        ),
        "Offer Help": (
            "*Help Offer*\n\n"
            "Please provide the following information in a single message:\n\n"
            "1. Type of help you can provide (rescue, medical, supplies, etc.)\n"
            "2. Your location\n"
            "3. Resources available (vehicles, equipment, etc.)\n"
            "4. Your contact information\n\n"
            "*Note:* You can add a photo in the next step."
        )
    }
    
    return instructions.get(report_type, "Please provide all relevant information in a single message.")

def determine_urgency(text: str) -> str:
    """Determine urgency level based on text content."""
    text = text.lower()
    if "critical" in text or "emergency" in text or "urgent" in text or "life threatening" in text:
        return "Critical (Medical Emergency)"
    elif "high" in text or "trapped" in text or "injured" in text:
        return "High (Trapped/Missing)"
    elif "medium" in text or "safe" in text:
        return "Medium (Safe but Separated)"
    return "Low (Information Only)"

def format_report_message(user_data: dict, report_id: str, priority_icon: str, timestamp: str, user) -> str:
    """Format the report message."""
    return (
        f"{priority_icon} *{user_data['report_type']}* {priority_icon}\n\n"
        f"*Report ID / အစီရင်ခံအမှတ်:* `{report_id}`\n\n"
        f"*Full Details / အပြည့်အစုံ:*\n{user_data['all_data']}\n\n"
        f"*Urgency / အရေးပေါ်အဆင့်:* {user_data['urgency']}\n\n"
        f"*Reported / အချိန်:* {timestamp}\n"
        f"*Reported by / တင်သွင်းသူ:* {user.first_name} {user.last_name or ''}"
    )

def store_report(report_id: str, user_data: dict, user, timestamp: str) -> None:
    """Store report in memory."""
    REPORTS[report_id] = {
        'report_type': user_data['report_type'],
        'all_data': user_data['all_data'],
        'urgency': user_data['urgency'],
        'timestamp': timestamp,
        'photo': user_data.get('photo_id'),  # Changed from 'photo' to 'photo_id' for consistency
        'user_id': user.id,
        'username': user.username
    }

# Inside send_report_to_channel function:
async def send_report_to_channel(bot, user_data: dict, safe_message: str) -> None:
    """Send report to the channel."""
    if user_data.get('photo_id'):  # Changed from 'photo' to 'photo_id' for consistency
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=user_data['photo_id'],  # Changed from 'photo' to 'photo_id'
            caption=safe_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=safe_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def send_confirmation_to_user(update, context, report_id):
    """Send confirmation message to user."""
    await update.message.reply_text(
        f"✅ Your report has been submitted successfully!\n\n"
        f"📝 *Report ID:* `{report_id}`\n\n"
        f"Please save this ID for future reference. You can use it to track "
        f"updates or provide additional information later.\n\n"
        f"သင့်အစီရင်ခံစာ အောင်မြင်စွာ တင်သွင်းပြီးပါပြီ။ အစီရင်ခံအမှတ်ကို မှတ်သားထားပါ။",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_report_error(update, error):
    """Handle errors during report submission."""
    logger.error(f"Error in report submission: {str(error)}")
    await update.message.reply_text(
        "❌ There was an error submitting your report. Please try again later."
    )

# Add the new functions for searching missing persons and contacting reporters

async def search_missing_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for a missing person by name or details."""
    search_query = update.message.text.strip()
    logger.info(f"Searching for missing person with query: '{search_query}'")
    
    # Store the search query for later use
    context.user_data['search_query'] = search_query
    
    matching_reports = []
    
    # First try database search
    try:
        db_reports = search_reports_by_content(search_query, report_type="Missing Person (Earthquake)")
        if db_reports:
            matching_reports.extend(db_reports)
    except Exception as e:
        logger.error(f"Database search error: {str(e)}")
    
    # Also search in-memory reports as fallback
    memory_matches = []
    for report_id, report in REPORTS.items():
        if report['report_type'] == "Missing Person (Earthquake)" and search_query.lower() in report['all_data'].lower():
            # Create a simplified report object similar to DB results
            memory_matches.append({
                'report_id': report_id,
                'details': report['all_data'],
                'user_id': report['user_id'],
                'username': report.get('username', ''),
                'created_at': report['timestamp']
            })
    
    matching_reports.extend(memory_matches)
    
    # Save matches in context for later reference
    context.user_data['matching_reports'] = matching_reports
    
    if matching_reports:
        # Format results for display
        result_text = ["*Found the following matching reports:*\n"]
        
        for i, report in enumerate(matching_reports, 1):
            # Extract first 100 chars of details for preview
            details_preview = report['details'][:100] + "..." if len(report['details']) > 100 else report['details']
            result_text.append(
                f"{i}. *Report ID:* `{report['report_id']}`\n"
                f"   {details_preview}\n"
            )
        
        result_text.append("\nTo contact someone about a specific report, reply with the number (e.g., '1', '2', etc.).")
        
        await update.message.reply_text(
            "\n".join(result_text),
            parse_mode=ParseMode.MARKDOWN
        )
        return SEND_MESSAGE_TO_REPORTER
    else:
        await update.message.reply_text(
            "No matching missing person reports found. Try a different search term or use /start to return to the main menu."
        )
        return ConversationHandler.END

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
            if 'details' in selected_report:
                # Extract name if possible
                lines = selected_report['details'].split('\n')
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
