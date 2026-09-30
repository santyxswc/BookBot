import os
import logging
import requests
import config

logger = logging.getLogger(__name__)

def download_book_file(url: str, book_id: str, extension: str) -> str:
    """
    Downloads a book file from the direct link to the temporary folder.
    Validates file size using headers before completing the download.
    
    Args:
        url (str): The resolved direct download link.
        book_id (str): The unique ID of the book (used to avoid filename collisions).
        extension (str): The file extension (e.g. pdf, epub).
        
    Returns:
        str: Absolute path to the downloaded file.
        
    Raises:
        ValueError: If the file size exceeds the Telegram bot limit.
        Exception: On network or writing errors.
    """
    # Create temp directory if it doesn't exist
    if not os.path.exists(config.TEMP_DOWNLOAD_DIR):
        os.makedirs(config.TEMP_DOWNLOAD_DIR)
        
    filename = f"book_{book_id}.{extension}"
    file_path = os.path.join(config.TEMP_DOWNLOAD_DIR, filename)
    
    # Generic User-Agent to avoid scraping blocks
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    logger.info(f"Initiating stream download from {url}")
    
    # Establish connection with stream=True
    response = requests.get(url, headers=headers, stream=True, timeout=60)
    response.raise_for_status()
    
    # Check file size prior to download if Content-Length header is present
    content_length = response.headers.get('Content-Length')
    if content_length:
        size_bytes = int(content_length)
        size_mb = size_bytes / (1024 * 1024)
        logger.info(f"Target file size from headers: {size_mb:.2f} MB")
        
        if size_mb > config.MAX_FILE_SIZE_MB:
            response.close() # Close stream
            raise ValueError(f"El archivo es demasiado grande ({size_mb:.1f} MB). El límite de envío en Telegram es de {config.MAX_FILE_SIZE_MB} MB.")
            
    # Download file in chunks
    with open(file_path, "wb") as f:
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                
        # If Content-Length was not available, check downloaded size now
        actual_size_mb = downloaded / (1024 * 1024)
        if not content_length and actual_size_mb > config.MAX_FILE_SIZE_MB:
            # Clean up immediately if it exceeds limit mid-download
            try:
                os.remove(file_path)
            except:
                pass
            raise ValueError(f"El archivo descargado ({actual_size_mb:.1f} MB) supera el límite de {config.MAX_FILE_SIZE_MB} MB de Telegram.")
            
    logger.info(f"Download finished successfully. Local file: {file_path}")
    return os.path.abspath(file_path)

def cleanup_file(file_path: str):
    """
    Safely deletes a local file from the disk.
    
    Args:
        file_path (str): Path to the file.
    """
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f"Temporary file deleted: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete temporary file {file_path}: {e}")
