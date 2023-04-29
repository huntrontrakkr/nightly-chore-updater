import os
import logging
import logging.handlers
from datetime import date, timedelta
from pprint import pprint

from notion_client import Client, APIResponseError
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
notion = Client(auth=os.environ["NOTION_API_KEY"], log_level=logging.DEBUG)

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
    notion.pages.update(
        page_id,
        properties={
            "Status": {"status": {"name": new_status}},
            "Last Completed": {"date": {"start": last_completed.isoformat()}},
        },
    )


def find_title_property(properties):
    for key, prop in properties.items():
        if prop['type'] == 'title':
            return key, prop
    return None, None


def process_pages(database_id):
    today = date.today()
    yesterday = today - timedelta(days=1)

    try:
        pages = notion.databases.query(
            database_id,
            filter={"property": "Status", "status": {"equals": "Done"}},
        ).get("results")
    except APIResponseError as error:
        logger.error(f"Error querying pages: {error}")
        return []

    changed_fields = []

    for page in pages:
        try:
            status = page["properties"]["Status"]["status"]["name"]
            due_next = page["properties"]["Due Next"]["formula"]["date"]["start"]
            due_next = date.fromisoformat(due_next)
        except KeyError as e:
            logger.error(f"Error processing page {page['id']}: missing property {e}")
            continue

        # Find the 'title' property by its 'id'
        title_property_id = None
        for prop_id, prop in page["properties"].items():
            if prop["type"] == "title":
                title_property_id = prop_id
                break

        if not title_property_id:
            logger.error(f"Error processing page {page['id']}: 'title' property not found")
            continue

        if status == "Done" and due_next <= yesterday:
            page_title = page["properties"][title_property_id]["title"][0]["plain_text"]
            logger.info(f"Processing page '{page_title}' (ID: {page['id']})")
            update_page(page["id"], "Not started", today)
            changed_fields.append({"page_id": page["id"], "title": page_title})
            logger.info(f"Processing page (ID: {page['id']})")

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
