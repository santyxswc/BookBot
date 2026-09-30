import os
import logging
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)

import config
from book_search import search_books, get_direct_link
from download import download_book_file, cleanup_file

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_CATEGORY, WAITING_QUERY, DISPLAYING_RESULTS = range(3)

# Results per page
BOOKS_PER_PAGE = 5

def sanitize_filename(name):
    """
    Cleans up a string to make it a safe filename.
    """
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = clean.strip()
    return clean[:80] if clean else "book"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Starts the conversation and displays the category choosing menu.
    """
    logger.info("Bot started /buscar command initiated.")
    
    # We build the category selection menu using Inline Keyboard buttons
    keyboard = [
        [
            InlineKeyboardButton("📚 Libro Informativo / Académico", callback_data="cat_informativo")
        ],
        [
            InlineKeyboardButton("📖 Novela / Literatura (Ficción)", callback_data="cat_novela")
        ],
        [
            InlineKeyboardButton("🏛️ Historia / Biografía", callback_data="cat_historia")
        ],
        [
            InlineKeyboardButton("🎨 Cómic / Manga", callback_data="cat_comic"),
            InlineKeyboardButton("🔬 Artículo Científico", callback_data="cat_articulo")
        ],
        [
            InlineKeyboardButton("❌ Cancelar Búsqueda", callback_data="cat_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 ¡Hola! Bienvenido al **Bot de Descarga de Libros**.\n\n"
        "Puedo ayudarte a buscar y descargar libros gratis de Library Genesis.\n\n"
        "💡 *Por favor, selecciona qué tipo de libro estás buscando hoy:* "
    )
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # If triggered from a callback query
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    return CHOOSING_CATEGORY

async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the user's category selection.
    """
    query = update.callback_query
    await query.answer()
    
    category_data = query.data
    
    if category_data == "cat_cancel":
        await query.edit_message_text("❌ Operación cancelada. Escribe /buscar cuando quieras empezar de nuevo.")
        return ConversationHandler.END
        
    category = category_data.replace("cat_", "")
    context.user_data['search_category'] = category
    
    # Category display text
    cat_names = {
        "informativo": "Libro Informativo / Académico 📚",
        "novela": "Novela / Literatura (Ficción) 📖",
        "historia": "Historia / Biografía 🏛️",
        "comic": "Cómic / Manga 🎨",
        "articulo": "Artículo Científico 🔬"
    }
    
    cat_name = cat_names.get(category, "General")
    context.user_data['search_category_display'] = cat_name
    
    prompt_text = (
        f"Has seleccionado la categoría: *{cat_name}*\n\n"
        "✍️ Por favor, escribe el **título, autor o término** de búsqueda (mínimo 3 caracteres):"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Cambiar Categoría", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        prompt_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_QUERY

async def process_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Receives and processes the search query.
    """
    query_text = update.message.text.strip()
    category = context.user_data.get('search_category', 'informativo')
    
    if len(query_text) < 3:
        await update.message.reply_text(
            "⚠️ La búsqueda debe tener al menos 3 caracteres. Por favor, escribe un término más largo:"
        )
        return WAITING_QUERY
        
    searching_msg = await update.message.reply_text("🔍 Buscando en los servidores de Libgen... por favor espera.")
    
    # Run synchronous search in an executor thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, search_books, query_text, category)
    
    if not results:
        await searching_msg.delete()
        await update.message.reply_text(
            "❌ No se encontraron libros con ese término en esta categoría.\n\n"
            "Intenta escribir de otra forma, busca en inglés o intenta con otra categoría.\n\n"
            "✍️ Escribe un nuevo término para buscar o /cancel para salir:"
        )
        return WAITING_QUERY
        
    # Store results in user_data
    context.user_data['search_results'] = results
    context.user_data['current_page'] = 0
    context.user_data['search_query'] = query_text
    
    # Delete the searching status message
    await searching_msg.delete()
    
    # Display results page
    await send_results_page(update, context, new_message=True)
    return DISPLAYING_RESULTS

async def send_results_page(update: Update, context: ContextTypes.DEFAULT_TYPE, new_message: bool = False):
    """
    Sends or edits the results message with pagination and selection buttons.
    """
    results = context.user_data.get('search_results', [])
    page = context.user_data.get('current_page', 0)
    query_text = context.user_data.get('search_query', '')
    cat_name = context.user_data.get('search_category_display', 'General')
    
    total_results = len(results)
    total_pages = (total_results + BOOKS_PER_PAGE - 1) // BOOKS_PER_PAGE
    
    start_idx = page * BOOKS_PER_PAGE
    end_idx = min(start_idx + BOOKS_PER_PAGE, total_results)
    
    page_items = results[start_idx:end_idx]
    
    # Build text response
    text = (
        f"🔍 *Resultados para:* '{query_text}'\n"
        f"📂 *Categoría:* {cat_name}\n"
        f"📄 *Página:* {page + 1} de {total_pages} (Total: {total_results})\n\n"
    )
    
    for i, book in enumerate(page_items):
        item_num = i + 1
        # Escape markdown characters to avoid formatting bugs
        title = book.title.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
        author = book.author.replace('*', '').replace('_', '') if book.author else "Desconocido"
        publisher = book.publisher.replace('*', '').replace('_', '') if book.publisher else "-"
        
        text += (
            f"**{item_num}.** 📘 *{title}*\n"
            f"   👤 Autor: {author}\n"
            f"   📂 {book.extension.upper()} | 💾 {book.size} | 📅 {book.year}\n"
            f"   🏢 Editorial: {publisher}\n\n"
        )
        
    # Build inline keyboard
    # Row 1: Number buttons for choosing which book on the page to download
    dl_buttons = []
    for i in range(len(page_items)):
        dl_buttons.append(
            InlineKeyboardButton(str(i + 1), callback_data=f"dl_{i}")
        )
    keyboard = [dl_buttons]
    
    # Row 2: Navigation (Previous / Next)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data="page_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data="page_next"))
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    # Row 3: Action actions (New Search, Cancel)
    keyboard.append([
        InlineKeyboardButton("🔎 Nueva Búsqueda", callback_data="btn_new_search"),
        InlineKeyboardButton("❌ Salir", callback_data="btn_exit")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if new_message and update.message:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Edit existing message
        query = update.callback_query
        if query:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

async def results_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles callbacks during results display (pagination, selection, actions).
    """
    query = update.callback_query
    await query.answer()
    
    data = query.data
    results = context.user_data.get('search_results', [])
    page = context.user_data.get('current_page', 0)
    
    if data == "page_prev":
        context.user_data['current_page'] = max(0, page - 1)
        await send_results_page(update, context, new_message=False)
        return DISPLAYING_RESULTS
        
    elif data == "page_next":
        total_pages = (len(results) + BOOKS_PER_PAGE - 1) // BOOKS_PER_PAGE
        context.user_data['current_page'] = min(total_pages - 1, page + 1)
        await send_results_page(update, context, new_message=False)
        return DISPLAYING_RESULTS
        
    elif data == "btn_new_search":
        # Reset current category details but go back to wait for a query in same category
        cat_name = context.user_data.get('search_category_display', 'General')
        await query.edit_message_text(
            f"🔎 Categoría actual: *{cat_name}*\n\n"
            "✍️ Escribe tu nueva búsqueda:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cambiar Categoría", callback_data="back_to_menu")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_QUERY
        
    elif data == "btn_exit":
        await query.edit_message_text("👋 Búsqueda finalizada. Escribe /buscar cuando desees buscar otro libro.")
        return ConversationHandler.END
        
    elif data.startswith("dl_"):
        # Download button clicked
        offset = int(data.split("_")[1])
        book_index = page * BOOKS_PER_PAGE + offset
        
        if book_index >= len(results):
            await query.edit_message_text("❌ Error: Índice de libro no válido.")
            return DISPLAYING_RESULTS
            
        book = results[book_index]
        
        # We start the downloading flow
        status_msg = await query.edit_message_text(
            f"🔄 Generando enlace de descarga seguro para:\n*'{book.title}'*...\n\n"
            "⏳ Esto puede tomar unos segundos.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        loop = asyncio.get_event_loop()
        
        # 1. Resolve direct download link
        download_url = await loop.run_in_executor(None, get_direct_link, book)
        
        if not download_url:
            await status_msg.edit_text(
                f"❌ No pudimos obtener un enlace de descarga válido para este espejo.\n\n"
                f"Intenta con otro resultado o formato.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results")]])
            )
            return DISPLAYING_RESULTS
            
        # 2. Check size and download if <= 50MB
        await status_msg.edit_text(
            f"📥 Enlace obtenido. Descargando el archivo (Peso: {book.size})...\n\n"
            "Por favor, mantén la calma y espera.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        file_path = None
        try:
            # Run streaming download in thread pool to avoid freezing the event loop
            file_path = await loop.run_in_executor(
                None, 
                download_book_file, 
                download_url, 
                book.id, 
                book.extension
            )
            
            # File downloaded successfully, now send it as Telegram document
            # Clean title/author for markdown caption and filename
            clean_filename = f"{sanitize_filename(book.title)}.{book.extension}"
            safe_title = book.title.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')
            safe_author = (book.author or 'Desconocido').replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')

            # Send document to user with markdown, fallback to plain text if Telegram fails entity parsing
            with open(file_path, 'rb') as doc:
                caption_md = f"✅ *¡Tu libro está listo!*\n\n📖 *{safe_title}*\n👤 Autor: {safe_author}\n📂 Formato: {book.extension.upper()} | Tamaño: {book.size}"
                try:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=doc,
                        filename=clean_filename,
                        caption=caption_md,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as md_err:
                    logger.warning(f"Markdown caption failed ({md_err}), retrying send_document with plain text caption")
                    doc.seek(0)
                    caption_plain = f"✅ ¡Tu libro está listo!\n\n📖 {book.title}\n👤 Autor: {book.author or 'Desconocido'}\n📂 Formato: {book.extension.upper()} | Tamaño: {book.size}"
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=doc,
                        filename=clean_filename,
                        caption=caption_plain
                    )
                
            await status_msg.delete() # Remove status message
            
        except ValueError as val_err:
            # File exceeds max size (50MB limit)
            logger.warning(f"File size limit validation triggered: {val_err}")
            oversize_text = (
                f"⚠️ **Archivo muy grande:** {book.size}\n\n"
                "Telegram limita las descargas directas de bots a un máximo de **50 MB**.\n\n"
                "🔗 Sin embargo, puedes descargarlo de forma segura desde tu navegador usando este enlace directo:\n\n"
                f"[📥 Descargar desde el navegador]({download_url})"
            )
            await status_msg.edit_text(
                oversize_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as err:
            logger.error(f"Error downloading or sending book: {err}", exc_info=True)
            await status_msg.edit_text(
                f"❌ Ocurrió un error al descargar o enviar el archivo.\n\n"
                f"Detalles: {str(err)}\n\n"
                "Puedes intentar descargar otro resultado.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results")]])
            )
            
        finally:
            # Make sure to cleanup file immediately to save server space
            if file_path:
                await loop.run_in_executor(None, cleanup_file, file_path)
                
        # Send confirmation message and prompt user if they want to continue
        keyboard_done = [
            [
                InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results"),
                InlineKeyboardButton("🔎 Nueva Búsqueda", callback_data="btn_new_search")
            ],
            [
                InlineKeyboardButton("❌ Salir", callback_data="btn_exit")
            ]
        ]
        
        # Check if chat still has status message active, or send new menu to avoid hanging state
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="💬 ¿Deseas descargar otro libro o realizar otra búsqueda?",
                reply_markup=InlineKeyboardMarkup(keyboard_done)
            )
        except Exception as send_err:
            logger.error(f"Error sending done keyboard: {send_err}")
            
        return DISPLAYING_RESULTS

async def back_to_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Returns to displaying search results.
    """
    query = update.callback_query
    await query.answer()
    await send_results_page(update, context, new_message=False)
    return DISPLAYING_RESULTS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancels the conversation and wipes active user search data.
    """
    logger.info("User cancelled search conversation.")
    
    # Clean cache
    context.user_data.pop('search_results', None)
    context.user_data.pop('current_page', None)
    context.user_data.pop('search_query', None)
    context.user_data.pop('search_category', None)
    
    cancel_text = "👋 Operación cancelada. Escribe /buscar cuando quieras buscar un libro."
    if update.message:
        await update.message.reply_text(cancel_text)
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(cancel_text)
        
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Prints a helper menu to the user.
    """
    help_text = (
        "📖 **Ayuda del Bot de Libros**\n\n"
        "Este bot te ayuda a descargar libros desde Library Genesis de forma sencilla.\n\n"
        "**Comandos disponibles:**\n"
        "/buscar o /start - Inicia el menú de búsqueda interactivo.\n"
        "/cancel - Cancela la búsqueda o descarga activa.\n"
        "/help - Muestra este mensaje de ayuda.\n\n"
        "**Instrucciones de Uso:**\n"
        "1. Selecciona la categoría en la que deseas buscar.\n"
        "2. Escribe el título o autor (mínimo 3 caracteres).\n"
        "3. Selecciona la página y el número del libro que deseas.\n"
        "4. El bot enviará el libro directamente si pesa menos de 50MB, o te dará el enlace de descarga directa en caso contrario."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

def main() -> None:
    """
    Builds and runs the Telegram bot application.
    """
    token = config.TELEGRAM_TOKEN
    
    if token == "TU_TOKEN_DE_TELEGRAM_AQUI" or not token:
        logger.error("ERROR CRÍTICO: No se ha configurado el Token de Telegram en el archivo .env")
        print("ERROR CRÍTICO: Debes poner tu Token de Telegram en el archivo .env antes de arrancar.")
        return
        
    logger.info("Starting Telegram Bot Application...")
    application = ApplicationBuilder().token(token).build()
    
    # Configure search conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("buscar", start),
            CommandHandler("start", start)
        ],
        states={
            CHOOSING_CATEGORY: [
                CallbackQueryHandler(category_chosen, pattern="^cat_.*$")
            ],
            WAITING_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_query),
                CallbackQueryHandler(start, pattern="^back_to_menu$")
            ],
            DISPLAYING_RESULTS: [
                CallbackQueryHandler(results_callback_handler, pattern="^(page_prev|page_next|btn_new_search|btn_exit|dl_\\d+)$"),
                CallbackQueryHandler(back_to_results, pattern="^back_to_results$"),
                CallbackQueryHandler(start, pattern="^back_to_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_query) # Let users write a new query directly
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cat_cancel$")
        ],
        allow_reentry=True
    )
    
    # Register handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    
    # Start bot
    application.run_polling()

if __name__ == '__main__':
    main()
