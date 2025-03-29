import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@lost_and_found_news")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")

# Store reports in memory (in a production app, this would be a database)
REPORTS = {}

# Priority levels
PRIORITIES = {
    "Critical (Medical Emergency)": "🔴",
    "High (Trapped/Missing)": "🟠",
    "Medium (Safe but Separated)": "🟡",
    "Low (Information Only)": "🟢"
}

# Volunteer Teams
VOLUNTEER_TEAMS = [
    {
        "name": "Team A",
        "phone": "09xxxxxxx",
        "info": "General rescue & medical."
    },
    {
        "name": "Team B",
        "phone": "09yyyyyyy",
        "info": "Food, water, and shelter assistance."
    },
    {
        "name": "Team C",
        "phone": "09zzzzzzz",
        "info": "Psychological support and counseling."
    },
]

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Export all constants
__all__ = ['BOT_TOKEN', 'CHANNEL_ID', 'ADMIN_IDS', 'REPORTS', 'PRIORITIES', 'VOLUNTEER_TEAMS', 'SUPABASE_URL', 'SUPABASE_KEY']
