# GoPro Telemetry Backend MVP

Backend FastAPI minimale ma funzionante per iniziare a provare:

- upload di video GoPro o compatibili (`.mp4`, `.mov`, `.m4v`)
- creazione job
- probing base del video con `ffprobe` se disponibile
- generazione di una telemetria **mock** strutturata come quella che servirà al frontend overlay
- endpoint preview per leggere i dati a un certo timestamp
- salvataggio di un render manifest da usare in una prima UI

## Perché questa versione è utile

Questa versione non estrae ancora la telemetria reale GoPro, ma ti mette in mano un backend vero con shape dati già sensata per:

- pagina upload
- pagina dettaglio job
- preview overlay in tempo reale nel browser
- futura integrazione con parser GoPro reale
- futuro export video con `ffmpeg`

## Requisiti

- Python 3.11+
- consigliato: `ffprobe` installato nel sistema

## Avvio

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Poi apri:

- API root: `http://127.0.0.1:8000/`
- docs Swagger: `http://127.0.0.1:8000/docs`

## Endpoint principali

### `POST /api/uploads`
Upload multipart con chiave `file`.

Risposta esempio:

```json
{
  "jobId": "job_1234567890",
  "status": "ready",
  "fileUrl": "/files/uploads/job_1234567890.mp4"
}
```

### `GET /api/jobs`
Lista job.

### `GET /api/jobs/{jobId}`
Dettaglio job completo.

### `GET /api/jobs/{jobId}/status`
Stato compatto per polling.

### `GET /api/jobs/{jobId}/telemetry`
Restituisce il JSON normalizzato con `video` e `samples`.

### `GET /api/jobs/{jobId}/preview?t=12.5`
Restituisce il sample più vicino a quel tempo e le label overlay già pronte.

### `POST /api/jobs/{jobId}/render`
Salva una configurazione di render e produce un manifest JSON.

Body esempio:

```json
{
  "theme": "minimal-dark",
  "units": "metric",
  "position": "bottom-left",
  "showSpeed": true,
  "showAltitude": true,
  "showCoordinates": true,
  "showMiniMap": false,
  "showTimestamp": true,
  "fontScale": 1.0,
  "margin": 24
}
```

## Forma dei dati preview

Esempio risposta di `/preview`:

```json
{
  "jobId": "job_xxx",
  "time": 12.5,
  "overlay": {
    "speedLabel": "31.2 km/h",
    "altitudeLabel": "126.8 m",
    "coordinatesLabel": "45.468100, 9.201220",
    "timestampLabel": "00:00:12"
  },
  "sample": {
    "t": 12.5,
    "lat": 45.4681,
    "lon": 9.20122,
    "alt": 126.8,
    "speed_kmh": 31.2,
    "heading": 145.2
  }
}
```

## Struttura progetto

```text
app/
  api/
    jobs.py
    uploads.py
  models/
    job.py
  schemas/
    render.py
  services/
    job_store.py
    processor.py
    telemetry.py
    video_info.py
  main.py

data/
  uploads/
  jobs/
```

## Prossimo step consigliato

1. Collegare un frontend Next.js con:
   - upload file
   - polling status
   - mappa
   - player video
   - preview overlay live con `/preview`
2. Sostituire `generate_mock_telemetry()` con parser reale GoPro.
3. Aggiungere worker e coda per processing asincrono.
4. Agganciare `ffmpeg` per render finale.

## Nota su telemetria reale GoPro

Il punto preciso da sostituire sarà in:

- `app/services/telemetry.py`

Lì puoi cambiare la funzione mock con una funzione del tipo:

```python
extract_gopro_telemetry(video_path: str) -> dict
```

che poi normalizza in questo stesso schema:

```json
{
  "video": { ... },
  "samples": [
    {
      "t": 0.0,
      "lat": 45.0,
      "lon": 9.0,
      "alt": 120.0,
      "speed_kmh": 18.5,
      "heading": 91.0
    }
  ]
}
```

Così il frontend non cambia quasi per niente.
