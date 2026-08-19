# Anki Spanish Vocab Builder

Pipeline en Python para generar un mazo de Anki (`.apkg`) de vocabulario español con:

- 🖼️ Imagen por palabra (vía [Pexels API](https://www.pexels.com/api/))
- 🔊 Audio de pronunciación generado por síntesis de voz (TTS)
- ✍️ Tarjetas de "escribir la respuesta" (español → inglés)
- 🏷️ Organización por tema mediante tags nativas de Anki

Creado originalmente para dar clases particulares de español, pero pensado para que cualquiera pueda adaptarlo a su propio idioma o lista de vocabulario.

## Estructura

```
data/          → lista de vocabulario fuente (palabra, traducción, tema, frase de ejemplo)
scripts/       → script que descarga imágenes/audio y genera el CSV + .apkg
templates/     → HTML/CSS de las tarjetas de Anki (Front, Back, Styling)
media/         → imágenes y audio descargados (generado, no versionado)
```

## Requisitos

- Python 3.10+
- Una clave de API de [Pexels](https://www.pexels.com/api/) (gratis, instantánea, sin tarjeta)
- Una clave de un proveedor de TTS (Azure o Google Cloud — ver sección abajo)

## Configuración

1. Clona el repositorio
2. Copia `.env.example` como `.env` y rellena tus claves
3. Instala las dependencias: `pip install -r requirements.txt`
4. Edita `data/word_list.py` con tu propio vocabulario
5. Ejecuta el script: `python scripts/build_csv.py`
6. El `.apkg` final se genera en `output/`, listo para importar en Anki

## Licencia

MIT — libre para usar, modificar y compartir.
