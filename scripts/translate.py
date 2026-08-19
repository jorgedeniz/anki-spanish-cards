import csv
import requests
import os
import hashlib

AZURE_TRANSLATOR_KEY = os.environ["AZURE_TRANSLATOR_KEY_1"]
AZURE_TRANSLATOR_REGION = os.environ["AZURE_TRANSLATOR_REGION"]
ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

GENDER_ICONS = {"m": "♂", "f": "♀", "common": "⚥", "neutral": "∅"}

def translate_batch(words, to_lang="en", from_lang="es"):
  params = {"api-version": "3.0", "from": from_lang, "to": to_lang}
  headers = {
    "Ocp-Apim-Subscription-Key": AZURE_TRANSLATOR_KEY,
    "Ocp-Apim-Subscription-Region": AZURE_TRANSLATOR_REGION,
    "Content-Type": "application/json",
  }
  body = [{"text": w} for w in words]
  resp = requests.post(ENDPOINT, params=params, headers=headers, json=body, timeout=30)
  resp.raise_for_status()
  return [item["translations"][0]["text"] for item in resp.json()]

def id_estable(word):
  """Derived ID from the content of the word (not its position in the file),
  so it stays the same even if it's rearranged or rebuilt."""
  return hashlib.md5(word.encode("utf-8")).hexdigest()[:8]

with open("data/frequency_candidates_reviewed.csv", encoding="utf-8") as f:
  candidates = list(csv.DictReader(f))

lemmas = [row["lemma"] for row in candidates]

# Azure Translator accepts up to 100 texts per request
translations = []
for i in range(0, len(lemmas), 100):
  batch = lemmas[i:i+100]
  translations.extend(translate_batch(batch))

lines = []
for row, translation in zip(candidates, translations):
  lines.append({
    "ID": id_estable(row["lemma"]),
    "Palabra_ES": row["lemma"],
    "Categoria": row["pos"].lower(),
    "Genero": GENDER_ICONS.get(row["gender"], ""),
    "Traduccion_EN": translation.lower(),
    "Traducciones_alt": "",
    "Frase_ejemplo": "",
    "Tema": "",
  })

with open("data/word_list_full.csv", "w", encoding="utf-8", newline="") as f:
  writer = csv.DictWriter(f, fieldnames=list(lines[0].keys()))
  writer.writeheader()
  writer.writerows(lines)

print(f"{len(lines)} total words in data/word_list_full.csv")