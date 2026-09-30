import sys
import os

# Reconfigure stdout for UTF-8 output on Windows consoles if available
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Check if running as a standalone executable (PyInstaller) or in virtualenv
is_frozen = getattr(sys, 'frozen', False)
is_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)

if not is_frozen and not is_venv:
    print("\n" + "!" * 60)
    print("ADVERTENCIA: No estas ejecutando el bot en su entorno virtual (.venv).")
    print("Esto causara errores de importacion de dependencias (ModuleNotFoundError).")
    print("\nPor favor, ejecuta el bot en tu terminal usando el comando:")
    print("   .venv\\Scripts\\python.exe main.py")
    print("!" * 60 + "\n")
    sys.exit(1)

import logging
from bot import main

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    try:
        logger.info("Initializing Telegram Book Downloader Bot from main.py...")
        main()
    except KeyboardInterrupt:
        logger.info("Bot execution interrupted by user. Shutting down gracefully.")
    except Exception as e:
        logger.error(f"Critical error during bot execution: {e}", exc_info=True)
