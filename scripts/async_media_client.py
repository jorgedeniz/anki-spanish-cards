import asyncio
import csv
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

import aiohttp
from azure.storage.blob.aio import BlobServiceClient

# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PIXABAY_API_KEY = os.environ["PIXABAY_API_KEY"]
AZURE_SPEECH_KEY_1 = os.environ["AZURE_SPEECH_KEY_1"]
AZURE_SPEECH_REGION = os.environ["AZURE_SPEECH_REGION"]
AZURE_STORAGE_CONNECTION_STRING_1 = os.environ["AZURE_STORAGE_CONNECTION_STRING_1"]
TTS_ENDPOINT = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
CONTAINER_NAME = "anki-vocab-media"

def sanitize_name(text: str) -> str:
  """Transforms one word into a safe string for a file name:
  with no bars, spaces or accents (bonito/a -> bonito_a, día -> dia)."""
  text = text.replace("/", "_").replace(" ", "_")
  text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
  return re.sub(r"[^a-zA-Z0-9_]", "", text).lower()

@dataclass
class ClientStats:
  total: int = 0
  succes: int = 0
  failed: int = 0
  retries: int = 0
  rate_limit_hits: int = 0

  def resume(self) -> str:
    return (f"Total: {self.total} | Success: {self.succes} | "
            f"Fails: {self.failed} | Retries: {self.retries} | "
            f"Found 429: {self.rate_limit_hits}")

class AsyncMediaFetcher:
  """
  Asynchronous and reusable HTTP client:
  - Limits concurrency via semaphore
  - Retries with exponential backoff when 429/5xx, adhering to Retry-After
  - Proactive notification if the API exposes the remaining margin in the headers
  - Stats after execution
  """

  def __init__(self, max_concurrent: int = 5, max_retries: int = 4,
               rate_limit_header: Optional[str] = None, rate_limit_margin: int = 5):
    self.semaphore = asyncio.Semaphore(max_concurrent)
    self.max_retries = max_retries
    self.rate_limit_header = rate_limit_header
    self.rate_limit_margin = rate_limit_margin
    self.stats = ClientStats()

  async def _wait_if_necessary(self, response: aiohttp.ClientResponse):
    if not self.rate_limit_header:
      return
    remainings = response.headers.get(self.rate_limit_header)
    reset = response.headers.get("X-RateLimit-Reset")
    if remainings is not None and reset is not None and int(remainings) <= self.rate_limit_margin:
      wait = max(0, int(reset) - time.time()) + 1
      logging.info(f"⏸️ There are {remainings} remaining requests — Pausing {wait:.0f}s until restart")
      await asyncio.sleep(wait)

  async def request(self, session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> Optional[aiohttp.ClientResponse]:
    """Makes a request with retries, adhering the concurrency limit."""
    async with self.semaphore:
      response = None
      for attempt in range(1, self.max_retries + 1):
        self.stats.total += 1
        try:
          response = await session.request(method, url, **kwargs)
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
          logging.warning(f"🔌 Net error (attempt {attempt}/{self.max_retries}): {e}")
          if attempt < self.max_retries:
            self.stats.retries += 1
            await asyncio.sleep(2 ** attempt)
            continue
          self.stats.failed += 1
          return None

        if response.status == 200:
          self.stats.succes += 1
          await self._wait_if_necessary(response)
          return response

        if response.status == 429:
          self.stats.rate_limit_hits += 1
          wait = int(response.headers.get("Retry-After", 2 ** (attempt + 2)))
          logging.warning(f"⏳ 429 — Waiting {wait}s (attempt {attempt}/{self.max_retries})")
          self.stats.retries += 1
          await asyncio.sleep(wait)
          continue

        if response.status >= 500:
          wait = min(2 ** attempt, 60)
          logging.warning(f"🔄 Error {response.status} — retrying in {wait}s")
          self.stats.retries += 1
          await asyncio.sleep(wait)
          continue

        # Non-recoverable error (400, 401, 403, 404...) — No point in retrying
        logging.error(f"❌ HTTP {response.status} in {url} — no retry")
        self.stats.failed += 1
        return None

      self.stats.failed += 1
      return None

async def blob_exists(blob_service, blob_name: str) -> bool:
  blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=blob_name)
  return await blob_client.exists()

async def upload_to_blob(blob_service, blob_name: str, content: bytes):
  blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=blob_name)
  await blob_client.upload_blob(content, overwrite=True)

async def fetch_image(fetcher, session, blob_service, word_id: str, word_es: str, query: str) -> bool:
  blob_name = f"images/{word_id}_{sanitize_name(word_es)}.jpg"
  if await blob_exists(blob_service, blob_name):
    return True
  resp = await fetcher.request(
    session, "GET", "https://pixabay.com/api/",
    params={"key": PIXABAY_API_KEY, "q": query, "image_type": "all",
            "safesearch": "true", "per_page": 3}, # Minimum per_page allowed is 3
    timeout=aiohttp.ClientTimeout(total=30),
  )
  if resp is None:
    return False
  data = await resp.json()
  hits = data.get("hits", [])
  if not hits:
    return False
  img_resp = await session.get(hits[0]["webformatURL"], timeout=aiohttp.ClientTimeout(total=30))
  content = await img_resp.read()
  await upload_to_blob(blob_service, blob_name, content)
  return True

async def generate_audio(fetcher, session, blob_service, word_id: str, word_es: str, voice: str = "es-ES-ElviraNeural") -> bool:
  blob_name = f"audios/{word_id}_{sanitize_name(word_es)}.mp3"
  if await blob_exists(blob_service, blob_name):
    return True
  ssml = f"<speak version='1.0' xml:lang='es-ES'><voice xml:lang='es-ES' name='{voice}'>{word_es}</voice></speak>"
  resp = await fetcher.request(
    session, "POST", TTS_ENDPOINT,
    headers={
      "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY_1,
      "Content-Type": "application/ssml+xml",
      "X-Microsoft-OutputFormat": "audio-16khz-64kbitrate-mono-mp3",
    },
    data=ssml.encode("utf-8"), timeout=aiohttp.ClientTimeout(total=30),
  )
  if resp is None:
    return False
  content = await resp.read()
  await upload_to_blob(blob_service, blob_name, content)
  return True

async def missing_media_resume(rows: list[dict], blob_service) -> None:
  """Checks which words have an image and audio in Blob Storage and which
  ones not, then prints a resume + a new CSV with only the incomplete ones"""
  remainings = []
  completed = 0

  for row in rows:
    sufix = sanitize_name(row["Palabra_ES"])
    has_image = await blob_exists(blob_service, f"images/{row['ID']}_{sufix}.jpg")
    has_audio = await blob_exists(blob_service, f"audios/{row['ID']}_{sufix}.mp3")

    if has_image and has_audio:
      completed += 1
    else:
      remainings.append({
        "ID": row["ID"],
        "Palabra_ES": row["Palabra_ES"],
        "Falta_imagen": "" if has_image else "si",
        "Falta_audio": "" if has_audio else "si",
      })

  only_image = sum(1 for r in remainings if r["Falta_imagen"] and not r["Falta_audio"])
  only_audio = sum(1 for r in remainings if r["Falta_audio"] and not r["Falta_imagen"])
  both = sum(1 for r in remainings if r["Falta_imagen"] and r["Falta_audio"])

  logging.info("📊 Media resume")
  logging.info(f"  Total of words: {len(rows)}")
  logging.info(f"  Completed (image + audio): {completed}")
  logging.info(f"  Only missing image: {only_image}")
  logging.info(f"  Only missing audio: {only_audio}")
  logging.info(f"  Both missing: {both}")

  if remainings:
    os.makedirs("output", exist_ok=True)
    with open("output/missing_media.csv", "w", encoding="utf-8", newline="") as f:
      writer = csv.DictWriter(f, fieldnames=["ID", "Palabra_ES", "Falta_imagen", "Falta_audio"])
      writer.writeheader()
      writer.writerows(remainings)
    logging.info(f"  📄 Detail of the {len(remainings)} incompleted words in output/missing_media.csv")
  else:
    logging.info("  ✅ All the words have image and audio")

async def process_everything(rows: list[dict]):
  """Two independant fetchers: Each API with its own limit, so each
  'pipe' goes at its own pace instead of having the slowest one dragging the rest"""
  fetcher_images = AsyncMediaFetcher(max_concurrent=5, rate_limit_header="X-RateLimit-Remaining")
  fetcher_audio =AsyncMediaFetcher(max_concurrent=5)

  async with aiohttp.ClientSession() as session, BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING_1) as blob_service:
    images_tasks = (fetch_image(fetcher_images, session, blob_service, r["ID"], r["Palabra_ES"], r["Traduccion_EN"]) for r in rows)
    audio_tasks = (generate_audio(fetcher_audio, session, blob_service, r["ID"], r["Palabra_ES"]) for r in rows)

    # Both pipes run in parallel between them, not one after the other
    await asyncio.gather(asyncio.gather(*images_tasks), asyncio.gather(*audio_tasks))

    logging.info(f"Images — {fetcher_images.stats.resume()}")
    logging.info(f"Audio — {fetcher_audio.stats.resume()}")

    await missing_media_resume(rows, blob_service)

def main():
  with open("data/word_list_full.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
    asyncio.run(process_everything(rows))

if __name__ == "__main__":
  main()