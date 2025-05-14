import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv
import base64

# Logging einrichten
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Lade Umgebungsvariablen aus .env Datei
load_dotenv('secrets.env')

# API-Keys und Konfiguration aus Umgebungsvariablen
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GPT_API_KEY = os.getenv('OPENAI_API_KEY')
print(GPT_API_KEY)

# OpenAI Client initialisieren
client = OpenAI(api_key=GPT_API_KEY)

# Funktionen
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sendet eine Nachricht, wenn der Befehl /start genutzt wird."""
    await update.message.reply_text(
        'Hallo! Sende mir ein Bild und ich werde es analysieren.'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sendet eine Nachricht, wenn der Befehl /help genutzt wird."""
    await update.message.reply_text('Sende mir einfach ein Bild und ich werde es analysieren.')

def read_prompt_from_file(filename="prompt.txt"):
    """Liest den Prompt aus einer Textdatei."""
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt-Datei {filename} nicht gefunden.")
        return "Was ist auf diesem Bild zu sehen?"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verarbeitet empfangene Fotos und sendet sie an die GPT API."""
    # Informiere den Benutzer, dass das Bild verarbeitet wird
    await update.message.reply_text("Verarbeite dein Bild...")
    
    try:
        # Hole das Foto mit der höchsten Auflösung
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Konvertiere das Bild zu Base64
        base64_image = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Hole den Prompt aus der Textdatei
        prompt = read_prompt_from_file()
        
        # Verwende die OpenAI-Bibliothek für die Anfrage
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500
        )
        
        # Extrahiere die Antwort von GPT
        gpt_response = response.choices[0].message.content
        await update.message.reply_text(gpt_response)
    
    except Exception as e:
        logger.error(f"Fehler bei der Bildverarbeitung: {e}")
        await update.message.reply_text(
            "Entschuldigung, es gab einen Fehler bei der Verarbeitung deines Bildes."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Antwortet auf Textnachrichten."""
    await update.message.reply_text(
        "Bitte sende mir ein Bild zur Analyse."
    )

def main() -> None:
    """Startet den Bot."""
    # Erstelle den Application-Instanz mit dem Token
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Füge Handler hinzu
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Starte den Bot
    application.run_polling()

if __name__ == "__main__":
    main()