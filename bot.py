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


def sanitize_filename(name: str) -> str:
    """Cleans up a string to make it a safe filename."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = clean.strip()
    return clean[:80] if clean else "book"


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the main interactive keyboard for the bot."""
    keyboard = [
        [
            InlineKeyboardButton("🔍 Buscar Libros", callback_data="menu_search")
        ],
        [
            InlineKeyboardButton("ℹ️ ¿Cómo Funciona?", callback_data="menu_info"),
            InlineKeyboardButton("💖 Donaciones", callback_data="menu_donate")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_categories_keyboard() -> InlineKeyboardMarkup:
    """Returns category selection inline buttons."""
    keyboard = [
        [
            InlineKeyboardButton("📚 Informativo / Académico", callback_data="cat_informativo")
        ],
        [
            InlineKeyboardButton("📖 Novela / Ficción", callback_data="cat_novela")
        ],
        [
            InlineKeyboardButton("🏛️ Historia / Biografía", callback_data="cat_historia")
        ],
        [
            InlineKeyboardButton("🎨 Cómic / Manga", callback_data="cat_comic"),
            InlineKeyboardButton("🔬 Artículo Científico", callback_data="cat_articulo")
        ],
        [
            InlineKeyboardButton("⬅️ Volver al Menú Principal", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# ──────────────────────────────────────────────────────────────────────────────
# Main Menus & Informational Handlers
# ──────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Displays the Welcome Main Menu.
    """
    welcome_text = (
        "👋 **¡Bienvenido a BookBot!** 📚\n\n"
        "Tu asistente inteligente para encontrar y descargar libros, artículos "
        "académicos, novelas y cómics directamente en Telegram.\n\n"
        "✨ **Características:**\n"
        "• Búsqueda ultrarrápida en múltiples servidores en paralelo.\n"
        "• Descarga directa en formatos PDF, EPUB, MOBI, CBR y más.\n"
        "• Envíos de archivos directos al chat (hasta 50 MB).\n\n"
        "👇 *Selecciona una opción para comenzar:*"
    )

    reply_markup = get_main_menu_keyboard()

    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    return ConversationHandler.END


async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles callbacks from the initial main menu.
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_search":
        prompt_text = (
            "📂 **Selecciona la Categoría**\n\n"
            "Elige el tipo de lectura para optimizar los resultados de búsqueda:"
        )
        await query.edit_message_text(
            prompt_text,
            reply_markup=get_categories_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return CHOOSING_CATEGORY

    elif data == "menu_info":
        info_text = (
            "ℹ️ **¿Cómo funciona BookBot?**\n\n"
            "1️⃣ **Elige una categoría:** Académico, Novela, Historia, Cómic o Artículo.\n"
            "2️⃣ **Escribe tu búsqueda:** Título, autor o tema (mínimo 3 letras).\n"
            "3️⃣ **Explora los resultados:** Navega entre páginas y pulsa el número del libro que deseas.\n"
            "4️⃣ **Descarga instantánea:** Si el archivo pesa menos de 50 MB, el bot te lo enviará directamente. "
            "Si pesa más, te proporcionará un enlace de descarga rápida para tu navegador.\n\n"
            "💡 **Consejos:**\n"
            "• Si no encuentras un libro en español, prueba buscando el título original en inglés.\n"
            "• Sé conciso: 'Calculo Stewart' en vez de 'Libro completo de calculo trascendentes tempranas'."
        )
        keyboard = [
            [InlineKeyboardButton("🔍 Iniciar Búsqueda Ahora", callback_data="menu_search")],
            [InlineKeyboardButton("⬅️ Volver al Menú Principal", callback_data="menu_main")]
        ]
        await query.edit_message_text(
            info_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    elif data == "menu_donate":
        donation_url = getattr(config, "DONATION_URL", "https://ko-fi.com/santyxswc")
        donation_info = getattr(
            config, 
            "DONATION_INFO", 
            "¡Tu apoyo ayuda a mantener el bot activo, pagar servidores y continuar añadiendo mejoras!"
        )

        donate_text = (
            "💖 **Apoya el Proyecto BookBot**\n\n"
            "BookBot es un proyecto gratuito y de código abierto creado para facilitar el acceso a la lectura y educación.\n\n"
            f"☕ {donation_info}\n\n"
            "Cualquier contribución, por pequeña que sea, marca la diferencia y permite costear servidores y proxies para evitar bloqueos."
        )

        keyboard = [
            [InlineKeyboardButton("☕ Invítame un café / Donar", url=donation_url)],
            [InlineKeyboardButton("🔍 Ir a Buscar Libros", callback_data="menu_search")],
            [InlineKeyboardButton("⬅️ Menú Principal", callback_data="menu_main")]
        ]
        await query.edit_message_text(
            donate_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    elif data == "menu_main":
        await start(update, context)
        return ConversationHandler.END

    return ConversationHandler.END


async def start_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Direct shortcut command /buscar."""
    prompt_text = (
        "📂 **Selecciona la Categoría**\n\n"
        "Elige el tipo de lectura para optimizar los resultados de búsqueda:"
    )
    if update.message:
        await update.message.reply_text(
            prompt_text,
            reply_markup=get_categories_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            prompt_text,
            reply_markup=get_categories_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    return CHOOSING_CATEGORY


async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Direct command /donar."""
    donation_url = getattr(config, "DONATION_URL", "https://ko-fi.com/santyxswc")
    donate_text = (
        "💖 **Apoya el Proyecto BookBot**\n\n"
        "BookBot es un proyecto sin fines de lucro. Si te ha sido de utilidad, puedes apoyar su mantenimiento.\n\n"
        "¡Muchísimas gracias por tu generosidad!"
    )
    keyboard = [
        [InlineKeyboardButton("☕ Donar en Ko-fi / PayPal", url=donation_url)],
        [InlineKeyboardButton("🔍 Buscar Libros", callback_data="menu_search")]
    ]
    await update.message.reply_text(
        donate_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────────────────────
# Search & Results Conversation Flow
# ──────────────────────────────────────────────────────────────────────────────

async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's category selection."""
    query = update.callback_query
    await query.answer()

    category_data = query.data

    if category_data == "menu_main":
        await start(update, context)
        return ConversationHandler.END

    category = category_data.replace("cat_", "")
    context.user_data['search_category'] = category

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
        f"📂 Categoría: *{cat_name}*\n\n"
        "✍️ Por favor, escribe el **título, autor o término** a buscar (mínimo 3 caracteres):"
    )

    keyboard = [
        [InlineKeyboardButton("⬅️ Cambiar Categoría", callback_data="menu_search")],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        prompt_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_QUERY


async def process_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and processes the search query."""
    query_text = update.message.text.strip()
    category = context.user_data.get('search_category', 'informativo')

    if len(query_text) < 3:
        await update.message.reply_text(
            "⚠️ La búsqueda debe tener al menos 3 caracteres. Por favor, escribe un término más específico:"
        )
        return WAITING_QUERY

    searching_msg = await update.message.reply_text("⚡ Buscando en múltiples servidores... por favor espera.")

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, search_books, query_text, category)

    if not results:
        try:
            await searching_msg.delete()
        except Exception:
            pass

        keyboard = [
            [InlineKeyboardButton("🔄 Reintentar Búsqueda", callback_data="menu_search")],
            [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_main")]
        ]
        await update.message.reply_text(
            "❌ No se encontraron libros con ese término en esta categoría.\n\n"
            "💡 *Sugerencias:*\n"
            "• Intenta escribir solo palabras clave del título.\n"
            "• Prueba buscando en inglés o seleccionando otra categoría.\n\n"
            "✍️ Escribe otro término o usa el menú:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_QUERY

    context.user_data['search_results'] = results
    context.user_data['current_page'] = 0
    context.user_data['search_query'] = query_text

    try:
        await searching_msg.delete()
    except Exception:
        pass

    await send_results_page(update, context, new_message=True)
    return DISPLAYING_RESULTS


async def send_results_page(update: Update, context: ContextTypes.DEFAULT_TYPE, new_message: bool = False):
    """Sends or edits the results message with pagination and selection buttons."""
    results = context.user_data.get('search_results', [])
    page = context.user_data.get('current_page', 0)
    query_text = context.user_data.get('search_query', '')
    cat_name = context.user_data.get('search_category_display', 'General')

    total_results = len(results)
    total_pages = (total_results + BOOKS_PER_PAGE - 1) // BOOKS_PER_PAGE

    start_idx = page * BOOKS_PER_PAGE
    end_idx = min(start_idx + BOOKS_PER_PAGE, total_results)
    page_items = results[start_idx:end_idx]

    text = (
        f"🔍 *Resultados para:* '{query_text}'\n"
        f"📂 *Categoría:* {cat_name}\n"
        f"📄 *Página:* {page + 1} de {total_pages} (Total: {total_results})\n\n"
    )

    for i, book in enumerate(page_items):
        item_num = i + 1
        title = book.title.replace('*', '').replace('_', '').replace('[', '').replace(']', '')
        author = book.author.replace('*', '').replace('_', '') if book.author else "Desconocido"
        publisher = book.publisher.replace('*', '').replace('_', '') if book.publisher else "-"

        text += (
            f"**{item_num}.** 📘 *{title}*\n"
            f"   👤 Autor: {author}\n"
            f"   📂 {book.extension.upper()} | 💾 {book.size} | 📅 {book.year}\n"
            f"   🏢 Editorial: {publisher}\n\n"
        )

    # Row 1: Number buttons to download
    dl_buttons = [
        InlineKeyboardButton(str(i + 1), callback_data=f"dl_{i}")
        for i in range(len(page_items))
    ]
    keyboard = [dl_buttons]

    # Row 2: Navigation
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data="page_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data="page_next"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    # Row 3: Action buttons
    keyboard.append([
        InlineKeyboardButton("🔎 Nueva Búsqueda", callback_data="btn_new_search"),
        InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_main")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if new_message and update.message:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        query = update.callback_query
        if query:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )


async def results_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles pagination, download selection and navigation."""
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
        cat_name = context.user_data.get('search_category_display', 'General')
        await query.edit_message_text(
            f"🔎 Categoría actual: *{cat_name}*\n\n"
            "✍️ Escribe tu nueva búsqueda:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cambiar Categoría", callback_data="menu_search")],
                [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_main")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_QUERY

    elif data == "menu_main":
        await start(update, context)
        return ConversationHandler.END

    elif data.startswith("dl_"):
        offset = int(data.split("_")[1])
        book_index = page * BOOKS_PER_PAGE + offset

        if book_index >= len(results):
            await query.edit_message_text("❌ Error: Índice de libro no válido.")
            return DISPLAYING_RESULTS

        book = results[book_index]

        status_msg = await query.edit_message_text(
            f"🔄 Obteniendo enlace de descarga para:\n*'{book.title}'*...\n\n"
            "⏳ Un momento por favor.",
            parse_mode=ParseMode.MARKDOWN
        )

        loop = asyncio.get_event_loop()

        # 1. Resolve direct download link
        download_url = await loop.run_in_executor(None, get_direct_link, book)

        if not download_url:
            await status_msg.edit_text(
                "❌ No pudimos obtener un enlace de descarga activo para este archivo.\n\n"
                "Intenta con otro resultado o formato.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results")]])
            )
            return DISPLAYING_RESULTS

        # 2. Check and download
        await status_msg.edit_text(
            f"📥 Descargando archivo (*{book.size}*)...\n\n"
            "Enviándolo directamente por Telegram.",
            parse_mode=ParseMode.MARKDOWN
        )

        file_path = None
        try:
            file_path = await loop.run_in_executor(
                None,
                download_book_file,
                download_url,
                book.id,
                book.extension
            )

            clean_filename = f"{sanitize_filename(book.title)}.{book.extension}"
            safe_title = book.title.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')
            safe_author = (book.author or 'Desconocido').replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')

            with open(file_path, 'rb') as doc:
                caption_md = (
                    f"✅ *¡Tu libro está listo!*\n\n"
                    f"📖 *{safe_title}*\n"
                    f"👤 Autor: {safe_author}\n"
                    f"📂 Formato: {book.extension.upper()} | 💾 {book.size}\n\n"
                    "¡Disfruta tu lectura! 📚"
                )
                try:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=doc,
                        filename=clean_filename,
                        caption=caption_md,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as md_err:
                    logger.warning(f"Markdown caption failed ({md_err}), retrying plain text")
                    doc.seek(0)
                    caption_plain = f"✅ ¡Tu libro está listo!\n\n📖 {book.title}\n👤 Autor: {book.author or 'Desconocido'}\n📂 Formato: {book.extension.upper()} | 💾 {book.size}"
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=doc,
                        filename=clean_filename,
                        caption=caption_plain
                    )

            try:
                await status_msg.delete()
            except Exception:
                pass

        except ValueError as val_err:
            logger.warning(f"File size limit validation: {val_err}")
            oversize_text = (
                f"⚠️ **Archivo muy grande:** {book.size}\n\n"
                "Telegram limita los envíos directos de bots a **50 MB**.\n\n"
                "🔗 Puedes descargarlo de forma directa y segura en tu navegador:\n\n"
                f"[📥 Descargar desde el navegador]({download_url})"
            )
            await status_msg.edit_text(
                oversize_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results")]]),
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as err:
            logger.error(f"Error downloading/sending book: {err}", exc_info=True)
            await status_msg.edit_text(
                f"❌ Error al procesar el archivo: {str(err)}\n\n"
                "Puedes intentar con otro de los resultados.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results")]])
            )

        finally:
            if file_path:
                await loop.run_in_executor(None, cleanup_file, file_path)

        # Options after download
        keyboard_done = [
            [
                InlineKeyboardButton("⬅️ Volver a los Resultados", callback_data="back_to_results"),
                InlineKeyboardButton("🔎 Nueva Búsqueda", callback_data="btn_new_search")
            ],
            [
                InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_main")
            ]
        ]

        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="💬 ¿Deseas descargar otro libro o realizar una nueva búsqueda?",
                reply_markup=InlineKeyboardMarkup(keyboard_done)
            )
        except Exception as send_err:
            logger.error(f"Error sending done keyboard: {send_err}")

        return DISPLAYING_RESULTS


async def back_to_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Returns to displaying search results."""
    query = update.callback_query
    await query.answer()
    await send_results_page(update, context, new_message=False)
    return DISPLAYING_RESULTS


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels active conversation."""
    context.user_data.pop('search_results', None)
    context.user_data.pop('current_page', None)
    context.user_data.pop('search_query', None)
    context.user_data.pop('search_category', None)

    cancel_text = "👋 Operación cancelada. Escribe /start o /buscar cuando desees continuar."
    if update.message:
        await update.message.reply_text(cancel_text)
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(cancel_text)

    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays help text."""
    help_text = (
        "📖 **Ayuda de BookBot**\n\n"
        "**Comandos rápidos:**\n"
        "• /start o /menu - Menú principal interactivo.\n"
        "• /buscar - Inicia directamente el selector de búsqueda.\n"
        "• /info - Explicación detallada de cómo funciona el bot.\n"
        "• /donar - Información de donaciones y soporte al creador.\n"
        "• /cancel - Cancela la búsqueda actual.\n\n"
        "⚡ Los archivos se envían directo al chat si pesan menos de 50 MB."
    )
    keyboard = [
        [InlineKeyboardButton("🔍 Iniciar Búsqueda", callback_data="menu_search")],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_main")]
    ]
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


def main() -> None:
    """Builds and starts the Telegram bot application."""
    token = config.TELEGRAM_TOKEN

    if not token or token == "TU_TOKEN_AQUI":
        logger.error("ERROR CRÍTICO: No se ha configurado el TELEGRAM_TOKEN en .env")
        print("ERROR CRÍTICO: Debes configurar tu TELEGRAM_TOKEN en el archivo .env antes de iniciar.")
        return

    logger.info("Iniciando aplicación de Telegram BookBot...")
    application = ApplicationBuilder().token(token).build()

    # Search conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("buscar", start_search_command),
            CallbackQueryHandler(menu_callback_handler, pattern="^menu_(search|info|donate|main)$"),
        ],
        states={
            CHOOSING_CATEGORY: [
                CallbackQueryHandler(category_chosen, pattern="^(cat_.*|menu_main)$"),
                CallbackQueryHandler(menu_callback_handler, pattern="^menu_.*$")
            ],
            WAITING_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_query),
                CallbackQueryHandler(start_search_command, pattern="^menu_search$"),
                CallbackQueryHandler(start, pattern="^menu_main$")
            ],
            DISPLAYING_RESULTS: [
                CallbackQueryHandler(results_callback_handler, pattern="^(page_prev|page_next|btn_new_search|dl_\\d+|menu_main)$"),
                CallbackQueryHandler(back_to_results, pattern="^back_to_results$"),
                CallbackQueryHandler(start_search_command, pattern="^menu_search$"),
                CallbackQueryHandler(start, pattern="^menu_main$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_query)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CommandHandler("menu", start),
            CallbackQueryHandler(cancel, pattern="^cat_cancel$"),
            CallbackQueryHandler(start, pattern="^menu_main$")
        ],
        allow_reentry=True
    )

    # General commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(CommandHandler("donar", donate_command))
    application.add_handler(CommandHandler("info", help_command))
    application.add_handler(CommandHandler("help", help_command))

    # Conversation handler
    application.add_handler(conv_handler)

    # Direct callback fallback for menu buttons outside conversation
    application.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^menu_.*$"))

    # Run bot
    application.run_polling()


if __name__ == '__main__':
    main()
