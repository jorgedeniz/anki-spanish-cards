import csv
import requests
import spacy

FREQ_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/es/es_50k.txt"
TARGET_CANDIDATES = 2000
SCAN_WINDOW = 12000 # Lines of the frequency list to consider

GENDER_ICONS = { "Masc": "m", "Fem": "f" }
ACCEPTED_POS = { "NOUN", "VERB", "ADJ", "NUM", "PROPN" }
NO_GENDER_POS = { "VERB", "NUM", "ADJ" }

resp = requests.get(FREQ_URL, timeout=30)
resp.raise_for_status()
lines = resp.text.splitlines()

nlp = spacy.load("es_core_news_sm", disable=["parser", "ner"])

candidate_words = [line.split()[0] for line in lines[:SCAN_WINDOW] if len(line.split()) == 2]
docs = nlp.pipe(candidate_words, batch_size=200)

viewed = set()
results = []
for doc, original in zip(docs, candidate_words):
  if len(doc) == 0:
    continue
  tok = doc[0]
  if tok.pos_ not in ACCEPTED_POS or not tok.is_alpha:
    continue
  lemma = tok.lemma_.lower()
  if lemma in viewed:
    continue
  viewed.add(lemma)

  if tok.pos_ in NO_GENDER_POS:
    gender = "neutral"
  else:
    gender_morph = tok.morph.get("Gender")
    gender = GENDER_ICONS.get(gender_morph[0], "") if gender_morph else ""

  is_participle = "Part" in tok.morph.get("VerbForm")

  results.append({
    "lemma": lemma, "pos": tok.pos_, "gender": gender,
    "possible_participle": "yes" if is_participle else "",
  })

  if len(results) >= TARGET_CANDIDATES:
    break

if len(results) < TARGET_CANDIDATES:
  print(f"⚠️ Only {len(results)}/{TARGET_CANDIDATES} candidates were found in the"
        f"firsts {SCAN_WINDOW} lines - upgrade SCAN_WINDOW and try again if you want more")

with open("data/frequency_candidates.csv", "w", encoding="utf-8", newline="") as f:
  writer = csv.DictWriter(f, fieldnames=["lemma", "pos", "gender", "possible_participle"])
  writer.writeheader()
  writer.writerows(results)

print(f"{len(results)} candidates written in data/frequency_candidates.csv")
print(f"  No gender detected (check manually): {sum(1 for r in results if r['gender'] == '')}")
print(f"  Possible participles (decide if you want to keep them as adjectives): {sum(1 for r in results if r['possible_participle'])}")
print("⚠️  Check the file manually before continue — spaCy tags isolated words")
print("    without context, so it might have some category mistakes.")