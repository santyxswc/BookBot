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

# Donation and project info
DONATION_URL = os.getenv("DONATION_URL", "https://ko-fi.com/santyxswc")
DONATION_INFO = os.getenv(
    "DONATION_INFO", 
    "¡Tu apoyo ayuda a mantener el bot activo, pagar servidores y continuar añadiendo mejoras!"
)

# Create temporary downloads directory if it doesn't exist
if not os.path.exists(TEMP_DOWNLOAD_DIR):
    os.makedirs(TEMP_DOWNLOAD_DIR)