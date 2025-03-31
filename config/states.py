import logging
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_REPORT_TYPE = 0
CHOOSING_LOCATION = 1  # New state for location selection
COLLECTING_DATA = 2
PHOTO = 3
SEARCHING_REPORT = 4
SEND_MESSAGE = 5
DESCRIPTION = 6
SEARCH_MISSING_PERSON = 7
SEND_MESSAGE_TO_REPORTER = 8
SELECT_URGENCY = 9  # Added missing state for urgency selection
UPDATE_REPORT_STATUS = 10  # New state for updating report status
CHOOSE_STATUS = 11  # New state for choosing the status

# Check state definitions
logger.info(f"CHOOSING_REPORT_TYPE: {CHOOSING_REPORT_TYPE}")
logger.info(f"CHOOSING_LOCATION: {CHOOSING_LOCATION}")
logger.info(f"COLLECTING_DATA: {COLLECTING_DATA}")
logger.info(f"PHOTO: {PHOTO}")
logger.info(f"SEARCHING_REPORT: {SEARCHING_REPORT}")
logger.info(f"SEND_MESSAGE: {SEND_MESSAGE}")
logger.info(f"DESCRIPTION: {DESCRIPTION}")
logger.info(f"SEARCH_MISSING_PERSON: {SEARCH_MISSING_PERSON}")
logger.info(f"SEND_MESSAGE_TO_REPORTER: {SEND_MESSAGE_TO_REPORTER}")
logger.info(f"SELECT_URGENCY: {SELECT_URGENCY}")
logger.info(f"UPDATE_REPORT_STATUS: {UPDATE_REPORT_STATUS}")
logger.info(f"CHOOSE_STATUS: {CHOOSE_STATUS}")
