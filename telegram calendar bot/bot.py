import os
import logging
import json
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv
import base64
from icalendar import Calendar, Event
import tempfile

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
        'Hallo! Sende mir ein Bild von deinem Wochenplan und ich werde es in eine iCalendar-Datei umwandeln.'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sendet eine Nachricht, wenn der Befehl /help genutzt wird."""
    await update.message.reply_text('Sende mir einfach ein Bild deines Wochenplans und ich werde es in eine iCalendar-Datei umwandeln, die du in deinen Kalender importieren kannst.')

def read_prompt_from_file(filename="prompt.txt"):
    """Liest den Prompt aus einer Textdatei."""
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt-Datei {filename} nicht gefunden.")
        return "Was ist auf diesem Bild zu sehen?"

def json_to_ical(json_data):
    """Konvertiert JSON-Daten in eine iCalendar-Datei."""
    cal = Calendar()
    cal.add('prodid', '-//Wochenplan Bot//DE')
    cal.add('version', '2.0')

    json_data = json_data["entries"] if "entries" in json_data else json_data

    # Stelle sicher, dass json_data eine Liste ist
    if not isinstance(json_data, list):
        # Wenn es ein verschachteltes JSON ist, versuche, den richtigen Schlüssel zu finden
        if isinstance(json_data, dict):
            # Suche nach einem Listenwert in dem Dict
            for key, value in json_data.items():
                if isinstance(value, list) and len(value) > 0:
                    json_data = value
                    break
            else:
                # Wenn kein Listenwert gefunden wurde, packe das Dict in eine Liste
                json_data = [json_data]
        else:
            # Wenn es weder Liste noch Dict ist, erstelle eine leere Liste
            json_data = []

    for item in json_data:
        try:
            event = Event()
            
            # Standardwerte für fehlende Felder
            item_type = item.get('type', 'unknown')
            person = item.get('person')
            description = item.get('description')
            date_str = item.get('date')
            start_str = item.get('start')
            end_str = item.get('end')
            
            # Setze den Titel basierend auf Typ und Person
            if item_type == 'appointment':
                summary = f"Termin: {description or ''}"
                if person:
                    summary = f"{person} - {summary}"
            elif item_type == 'task':
                summary = f"Aufgabe: {description or ''}"
                if person:
                    summary = f"{person} - {summary}"
            elif item_type == 'workout':
                summary = f"Workout: {description or ''}"
            elif item_type == 'absence':
                summary = f"Abwesenheit: {person or ''}"
                if description:
                    summary += f" - {description}"
            else:
                summary = description or item.get('summary', 'Unbekannt')
            
            event.add('summary', summary)
            
            # Datum und Zeit
            # Datum (erforderlich)
            if date_str:
                try:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    # Falls Start- und Endzeit vorhanden
                    if start_str and end_str:
                        try:
                            start_time = datetime.strptime(start_str, "%H:%M").time()
                            end_time = datetime.strptime(end_str, "%H:%M").time()
                            start_datetime = datetime.combine(date_obj.date(), start_time)
                            end_datetime = datetime.combine(date_obj.date(), end_time)
                            event.add('dtstart', start_datetime)
                            event.add('dtend', end_datetime)
                        except ValueError:
                            # Wenn die Zeitformatierung fehlschlägt, als ganztägiges Ereignis behandeln
                            event.add('dtstart', date_obj.date())
                            event.add('X-MICROSOFT-CDO-ALLDAYEVENT', 'TRUE')
                    # Falls nur Startzeit vorhanden
                    elif start_str:
                        try:
                            start_time = datetime.strptime(start_str, "%H:%M").time()
                            start_datetime = datetime.combine(date_obj.date(), start_time)
                            # Standardmäßig 1 Stunde Dauer, wenn keine Endzeit angegeben
                            end_datetime = datetime.combine(date_obj.date(), start_time)
                            end_datetime = end_datetime.replace(hour=end_datetime.hour + 1)
                            event.add('dtstart', start_datetime)
                            event.add('dtend', end_datetime)
                        except ValueError:
                            # Wenn die Zeitformatierung fehlschlägt, als ganztägiges Ereignis behandeln
                            event.add('dtstart', date_obj.date())
                            event.add('X-MICROSOFT-CDO-ALLDAYEVENT', 'TRUE')
                    # Falls nur Datum vorhanden (ganztägige Ereignisse)
                    else:
                        event.add('dtstart', date_obj.date())
                        event.add('X-MICROSOFT-CDO-ALLDAYEVENT', 'TRUE')
                        event.add('X-APPLE-TRAVEL-ADVISORY-BEHAVIOR', 'AUTOMATIC')
                except ValueError:
                    # Wenn das Datumsformat falsch ist, überspringen wir diesen Eintrag
                    logger.warning(f"Ungültiges Datumsformat: {date_str} für Eintrag: {item}")
                    continue
            else:
                # Ohne Datum ist der Eintrag nicht gültig, überspringen
                logger.warning(f"Kein Datum für Eintrag: {item}")
                continue
            
            # Beschreibung
            description_text = ""
            if person and item_type != 'absence':
                description_text += f"Person: {person}\n"
            if description and item_type == 'absence':
                description_text += f"Beschreibung: {description}\n"
            if description_text:
                event.add('description', description_text)
            
            # Kategorie basierend auf Typ
            event.add('categories', [item_type.capitalize()])
            
            cal.add_component(event)
        except Exception as e:
            logger.error(f"Fehler beim Erstellen eines Kalendereintrags: {e} für Eintrag: {item}")
            continue
    
    return cal.to_ical()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verarbeitet empfangene Fotos und sendet sie an die GPT API."""
    # Informiere den Benutzer, dass das Bild verarbeitet wird
    processing_message = await update.message.reply_text("Verarbeite deinen Wochenplan...")
    
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
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "Du bist ein Assistent, der Wochenpläne aus Bildern in strukturiertes JSON umwandelt. Gib AUSSCHLIESSLICH das JSON zurück ohne Markdown-Formatierung oder zusätzlichen Text."
                },
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
            response_format={"type": "json_object"}
        )
        
        # Extrahiere die Antwort von GPT (sollte ein JSON sein)
        gpt_response = response.choices[0].message.content
        
        # Bereinige die Antwort von möglichen Markdown-Code-Blöcken
        cleaned_response = gpt_response
        
        # Entferne Markdown-Code-Block-Formatierung, falls vorhanden
        if "```json" in cleaned_response and "```" in cleaned_response:
            # Extrahiere den Inhalt zwischen den Code-Block-Markierungen
            start_index = cleaned_response.find("```json") + len("```json")
            end_index = cleaned_response.rfind("```")
            if start_index < end_index:
                cleaned_response = cleaned_response[start_index:end_index].strip()
        elif cleaned_response.startswith("```") and cleaned_response.endswith("```"):
            # Wenn es nur ``` ohne Spezifikation ist
            cleaned_response = cleaned_response[3:-3].strip()
        
        logger.info(f"Bereinigte Antwort: {cleaned_response[:100]}...")  # Logge die ersten 100 Zeichen
        
        try:
            # Versuche, das JSON zu parsen
            json_data = json.loads(cleaned_response)
            
            # Erzeuge iCalendar-Datei
            ical_data = json_to_ical(json_data)
            
            # Erstelle eine temporäre Datei für den iCalendar-Inhalt
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ics') as tmp_file:
                tmp_file_path = tmp_file.name
                tmp_file.write(ical_data)
            
            # Sende die Datei an den Benutzer
            await update.message.reply_document(
                document=open(tmp_file_path, 'rb'),
                filename='wochenplan.ics',
                caption="Hier ist dein Wochenplan als iCalendar-Datei."
            )
            
            # Lösche die temporäre Datei
            os.unlink(tmp_file_path)
            
            # Lösche die Verarbeitungsnachricht
            await processing_message.delete()
            
        except json.JSONDecodeError as e:
            logger.error(f"Konnte JSON nicht parsen: {e}\nAntwort: {cleaned_response[:200]}")
            await processing_message.edit_text(
                "Es gab ein Problem bei der Analyse deines Wochenplans. "
                "Die Antwort konnte nicht als JSON-Format erkannt werden. "
                "Bitte versuche es mit einem klareren Bild."
            )
    
    except Exception as e:
        logger.error(f"Fehler bei der Bildverarbeitung: {e}")
        await processing_message.edit_text(
            "Entschuldigung, es gab einen Fehler bei der Verarbeitung deines Bildes."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Antwortet auf Textnachrichten."""
    await update.message.reply_text(
        "Bitte sende mir ein Bild deines Wochenplans zur Analyse."
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