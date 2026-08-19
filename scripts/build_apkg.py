import csv
import io
import os
import re
import tempfile
import unicodedata
from pathlib import Path

import genanki
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from PIL import Image, ImageDraw

AZURE_STORAGE_CONNECTION_STRING = os.environ["AZURE_STORAGE_CONNECTION_STRING_1"]
CONTAINER_NAME = "anki-vocab-media"
MODEL_ID = 1607392319
DECK_ID = 2059400110
IMAGE_SIZE = (480, 400) # width, height — Same size for all the cards

def sanitize_name(text: str) -> str:
  """Transforms one word into a safe string for a file name:
  with no bars, spaces or accents (bonito/a -> bonito_a, día -> dia)."""
  text = text.replace("/", "_").replace(" ", "_")
  text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
  return re.sub(r"[^a-zA-Z0-9_]", "", text).lower()

def resize_image(original_data: bytes) -> bytes:
  """Resizes and crops (cover + centered crop) to IMAGE_SIZE, so
  all the images in the deck have the same size"""
  img = Image.open(io.BytesIO(original_data)).convert("RGB")
  img_w, img_h = img.size
  obj_w, obj_h = IMAGE_SIZE
  scale = max(obj_w / img_w, obj_h / img_h)
  new_size = (round(img_w * scale), round(img_h * scale))
  img = img.resize(new_size, Image.Resampling.LANCZOS)
  left = (img.width - obj_w) // 2
  up = (img.height - obj_h) // 2
  img = img.crop((left, up, left + obj_w, up + obj_h))
  output = io.BytesIO()
  img.save(output, format="JPEG", quality=85)
  return output.getvalue()

def generate_placeholder_image() -> bytes:
  """Image for 'No image available' with the same standard size, for the words to
  which Pixabay/IA could not find anything."""
  img = Image.new("RGB", IMAGE_SIZE, color=(230, 226, 216))
  draw = ImageDraw.Draw(img)
  text = "No image"
  bbox = draw.textbbox((0, 0), text)
  x = (IMAGE_SIZE[0] - (bbox[2] - bbox[0])) // 2
  y = (IMAGE_SIZE[1] - (bbox[3] - bbox[1])) // 2
  draw.text((x, y), text, fill=(120, 112, 96))
  output = io.BytesIO()
  img.save(output, format="JPEG", quality=85)
  return output.getvalue()

def download_temporary_media(rows: list[dict], destiny: Path) -> dict:
  """Downloads every blob to the tmp folder and returns the names of the saved files
  for each row (tags <img>/[sound:])."""
  blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
  names = {}
  for row in rows:
    sufix = sanitize_name(row["Palabra_ES"])
    name_img = f"{row["ID"]}_{sufix}.jpg"
    name_audio = f"{row["ID"]}_{sufix}.mp3"

    try:
      blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=f"images/{name_img}")
      data = resize_image(blob_client.download_blob().readall())
    except ResourceNotFoundError:
      print(f"⚠️ No image for {row["ID"]} ({row["Palabra_ES"]}) — Using placeholder")
      data = generate_placeholder_image()
    with open(destiny / name_img, "wb") as f:
      f.write(data)

    audio_ok = True
    try:
      blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=f"audios/{name_audio}")
      with open(destiny / name_audio, "wb") as f:
        f.write(blob_client.download_blob().readall())
    except ResourceNotFoundError:
      print(f"⚠️ No audio for {row["ID"]} ({row['Palabra_ES']}) — Card won't have audio")
      audio_ok = False

    names[row["ID"]] = (name_img, name_audio if audio_ok else None)
  return names

model = genanki.Model(
  MODEL_ID, "Vocabulario ES-EN",
  fields=[{"name": n} for n in ["Palabra_ES", "Genero", "Traduccion_EN",
                                "Traducciones_alt", "Imagen", "Audio", "Frase_ejemplo"]],
  templates=[{
    "name": "Card 1",
    "qfmt": open("templates/front_template.html", encoding="utf-8").read(),
    "afmt": open("templates/back_template.html", encoding="utf-8").read(),
  }],
  css=open("templates/styles.css", encoding="utf-8").read(),
)

with open("data/word_list_full.csv", encoding="utf-8") as f:
  rows = list(csv.DictReader(f))

deck = genanki.Deck(DECK_ID, "Español::Vocabulario")
media_files = []

with tempfile.TemporaryDirectory() as tmp:
  tmp_path = Path(tmp)
  names = download_temporary_media(rows, tmp_path)

  for row in rows:
    name_img, name_audio = names[row["ID"]]
    audio_field = f"[sound:{name_audio}]" if name_audio else ""
    note = genanki.Note(
      model=model,
      fields=[row["Palabra_ES"], row["Genero"], row["Traduccion_EN"],
              row["Traducciones_alt"], f'<img src="{name_img}">',
              audio_field, row["Frase_ejemplo"]],
      tags=row["Tema"].split() + [row["Categoria"]],
    )
    note.guid = genanki.guid_for(row["ID"])
    deck.add_note(note)
    media_files.append(str(tmp_path / name_img))
    if name_audio:
      media_files.append(str(tmp_path / name_audio))

  package = genanki.Package(deck)
  package.media_files = media_files
  os.makedirs("output", exist_ok=True)
  package.write_to_file("output/vocabulario_es_en.apkg")
  # The tmp folder is erased automatically here, when getting out of the "with"

print("✅ output/vocabulario_es_en.apkg successfully generated")