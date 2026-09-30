import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram configurations
# Reads from environment variable (preferred) and defaults to your token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Download configurations
TEMP_DOWNLOAD_DIR = os.getenv("TEMP_DOWNLOAD_DIR", "downloads")
# Telegram's bot upload size limit is 50MB
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))

# Create temporary downloads directory if it doesn't exist
if not os.path.exists(TEMP_DOWNLOAD_DIR):
    os.makedirs(TEMP_DOWNLOAD_DIR)