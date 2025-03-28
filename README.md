# Emergency Lost and Found Telegram Bot

A disaster response Telegram bot for connecting people during earthquakes and other emergencies. Report missing or found people, request rescue, offer help, and facilitate emergency communications.

---

## Setup

1. Clone this repository.
2. Install the required packages:
3. Create a `.env` file with your Telegram bot token:
4. Run the bot:

---

## Features

### Emergency Response
- **Report Missing Persons**: Submit details about missing people during disasters.
- **Report Found Persons**: Help connect families by reporting people you've found.
- **Request Rescue**: Submit urgent rescue requests with location details.
- **Offer Help**: Register your available resources and skills to assist others.

### Lost & Found Items
- **Report Lost Items**: Submit information about lost belongings.
- **Report Found Items**: Report items you've found to return to owners.
- **Attach Photos**: Include images with your reports or skip if unavailable.

### Search & Connect
- **Search by ID**: Look up specific reports using their unique ID.
- **Search for Missing Persons**: Find reports by name or description details.
- **Contact Report Submitters**: Send messages directly to people who submitted reports.
- **Reunification System**: Connect those searching for missing people with those who have found them.

### Multilingual Support
- Supports both **English** and **Myanmar** language instructions.
- Critical information displayed in both languages for maximum accessibility.

---

## Usage

1. Start a conversation with the bot by sending `/start`.
2. Select the appropriate report type from the menu.
3. Follow the instructions to provide all relevant information.
4. Attach a photo or click the "Skip Photo" button.
5. Your report will be assigned a unique ID for future reference.
6. To search for missing persons, select "Search for Missing Person" and enter details.
7. To contact someone about a report, select from search results or use "Contact Report Submitter."

---

## Report Types

- **Missing Person (Earthquake)**: Report someone missing during the earthquake.
- **Found Person (Earthquake)**: Report finding someone displaced by the disaster.
- **Lost Item**: Report personal belongings that have been lost.
- **Found Item**: Report items you've found that might belong to others.
- **Request Rescue**: Request emergency assistance at a specific location.
- **Offer Help**: Register your available resources to assist others.

---

## Commands

- `/start` - Begin the reporting or search process.
- `/help` - Get detailed help and guidance.
- `/menu` - View all available commands.
- `/volunteer` - View volunteer team contact information.
- `/cancel` - Cancel the current operation.
- `/getid` - Get your Telegram User ID and username.

---

## Project Structure

The project is organized with a modular architecture:

- **`app.py`**: Main entry point and bot initialization.
- **`handlers/`**: Callback functions for different conversation stages.
- **`utils/`**: Helper functions for database operations, message formatting, etc.
- **`config/`**: Configuration settings and state management.

---

## Detailed Running Instructions

1. Make sure you have Python 3.7+ installed on your system.
2. Navigate to the project directory:
3. Create a virtual environment (optional but recommended):
4. Activate the virtual environment:
   - On macOS/Linux:
   - On Windows:
5. Install the required dependencies:
6. Update the `.env` file with your actual Telegram bot token:
   - If you don't have a token, create a new bot via BotFather on Telegram.
7. Run the bot:
8. Once the bot is running, you should see log messages indicating successful startup.
9. Open Telegram and start a conversation with your bot.
10. Send the `/start` command to begin using the emergency response system.

---

## Disaster Response Best Practices

When using this bot during emergencies:

- **Be precise with locations**: Include detailed location information for missing/found persons.
- **Include contact details**: Always provide a way for others to contact you.
- **Note physical descriptions**: For missing or found persons, include distinctive features.
- **Save report IDs**: Keep track of your report IDs for future reference.
- **Update information**: If a situation changes (person found, no longer in need), update the bot.

---

## Contributing

Contributions to improve the bot are welcome. Please feel free to submit pull requests or open issues to suggest enhancements or report bugs.

---

## License

This project is distributed under the **MIT License**.
