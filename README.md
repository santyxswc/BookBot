# BookBot

Bot de Telegram desarrollado en Python para buscar y descargar libros, artículos académicos, novelas y cómics utilizando múltiples espejos de Library Genesis.

Permite consultar el catálogo directamente desde un chat o grupo, filtrar por tipo de contenido, paginar resultados y recibir el archivo directamente si pesa menos de 50 MB (o un enlace directo en caso de superar el límite de la API de Telegram).

---

## Características

- **Búsqueda concurrente:** Consulta varios mirrors en paralelo (`libgen.li`, `libgen.vg`, etc.) y responde con el primero disponible.
- **Filtrado por categorías:**
  - Libros informativos y académicos
  - Novelas y literatura (ficción)
  - Historia y biografías
  - Cómics y manga
  - Artículos científicos
- **Descarga directa:** Envía archivos en formatos habituales (`.pdf`, `.epub`, `.mobi`, etc.) como documento de Telegram.
- **Soporte para archivos grandes:** Si el libro excede los 50 MB, genera un enlace directo para descargarlo desde el navegador sin saturar el bot.
- **Caché en memoria:** Reduce el tiempo de respuesta en búsquedas repetidas y minimiza peticiones a los servidores.
- **Interfaz con botones inline:** Menú interactivo con navegación por páginas, selector numérico y opciones de ayuda.

---

## Requisitos

- Python 3.10 o superior
- Un token de bot generado a través de [@BotFather](https://t.me/BotFather) en Telegram

---

## Instalación

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/santyxswc/BookBot.git
   cd BookBot
   ```

2. **Crear y activar un entorno virtual:**
   ```bash
   # En Windows
   python -m venv .venv
   .venv\Scripts\activate

   # En Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Configuración

Copia el archivo de ejemplo `.env.example` y crea tu propio `.env`:

```bash
# En Windows (PowerShell)
Copy-Item .env.example .env

# En Linux / macOS / Bash
cp .env.example .env
```

Abre `.env` y define tus variables:

```env
TELEGRAM_TOKEN=tu_token_aqui_de_botfather
TEMP_DOWNLOAD_DIR=downloads
MAX_FILE_SIZE_MB=50
DONATION_URL=https://ko-fi.com/tu_usuario
```

---

## Uso

Para iniciar el bot ejecuta:

```bash
# Desde el entorno virtual
python main.py

# O en Windows usando el script incluido
iniciar_bot.bat
```

### Comandos disponibles

| Comando | Descripción |
|---|---|
| `/start` o `/menu` | Abre el menú principal con botones interactivos |
| `/buscar` | Inicia directamente la selección de categoría y búsqueda |
| `/info` | Muestra la guía rápida de uso y formatos soportados |
| `/donar` | Enlace para apoyar el mantenimiento del proyecto |
| `/cancel` | Cancela la búsqueda o proceso actual |

---

## Estructura del proyecto

```text
BookBot/
├── .env.example        # Plantilla de variables de entorno
├── .gitignore          # Archivos y carpetas excluidas de Git
├── book_search.py      # Lógica de scraping, espejos y resolución de links
├── bot.py              # Handlers de Telegram, estados y flujo de conversación
├── config.py           # Carga de configuraciones desde el entorno
├── download.py         # Descarga en streaming y limpieza de temporales
├── iniciar_bot.bat     # Acceso directo para ejecución en Windows
├── main.py             # Punto de entrada y validación del entorno
└── requirements.txt    # Dependencias del proyecto
```

---

## Dependencias principales

- `python-telegram-bot` (v20+)
- `requests`
- `beautifulsoup4`
- `python-dotenv`

---

## Aviso legal

Este software ha sido desarrollado con fines exclusivamente educativos y de aprendizaje sobre programación asíncrona, bots de mensajería y consumo de datos web. El usuario es responsable del uso que haga de esta herramienta y del material consultado.
