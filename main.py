import os
import logging
import logging.handlers
from datetime import date, timedelta
from notion_client import Client
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger("notion_script")
logger.setLevel(logging.INFO)
handler = logging.handlers.TimedRotatingFileHandler("notion_script.log", when="D", interval=30, backupCount=1)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Initialize Notion client with API key
notion = Client(auth=os.environ["NOTION_API_KEY"])

# Initialize Twilio client
twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
twilio_client = TwilioClient(twilio_account_sid,
                             twilio_auth_token) if twilio_account_sid and twilio_auth_token else None

# Get values from .env file
database_url = os.environ["NOTION_DATABASE_URL"]
phone_numbers = os.environ["PHONE_NUMBERS"].split(",")
twilio_phone_number = os.environ["TWILIO_PHONE_NUMBER"]


def get_database_id(database_url):
    database_id = database_url.split("/")[-1].replace("-", "")
    return database_id


def update_page(page_id, new_status, last_completed):
    notion.pages.update_properties(
        page_id,
        properties={
            "Status": {"select": {"name": new_status}},
            "Last Completed": {"date": {"start": last_completed.isoformat()}},
        },
    )


def process_pages(database_id):
    today = date.today()
    yesterday = today - timedelta(days=1)

    pages = notion.databases.query(
        **{
            "database_id": database_id,
            "filter": {"property": "Status", "select": {"equals": "Done"}},
        }
    ).get("results")

    changed_fields = []

    for page in pages:
        due_next = page["properties"]["Due Next"]["date"]["start"]
        due_next = date.fromisoformat(due_next)

        if due_next <= yesterday:
            logger.info(f"Processing page '{page['title']['plain_text']}' (ID: {page['id']})")
            update_page(page["id"], "Not Started", today)
            changed_fields.append({"page_id": page["id"], "title": page["title"]["plain_text"]})
            logger.info(
                f"Updated Status to 'Not Started' and set Last Completed to {today} for page '{page['title']['plain_text']}' (ID: {page['id']})")

    return changed_fields


def send_text_message(changed_fields, phone_numbers):
    if not changed_fields or not twilio_client:
        return

    message_body = "Updated pages:\n\n"
    for field in changed_fields:
        message_body += f"Page ID: {field['page_id']}\nTitle: {field['title']}\n\n"

    for phone_number in phone_numbers:
        twilio_client.messages.create(
            body=message_body,
            from_=twilio_phone_number,
            to=phone_number,
        )
        logger.info(f"Sent update notification to {phone_number}")


def main():
    logger.info("Script started")
    database_id = get_database_id(database_url)
    changed_fields = process_pages(database_id)
    send_text_message(changed_fields, phone_numbers)
    logger.info("Script finished")


if __name__ == "__main__":
    main()
