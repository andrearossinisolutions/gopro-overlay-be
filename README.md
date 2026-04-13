# GoPro Telemetry Backend MVP

Backend FastAPI per iniziare a provare:

- upload di video GoPro o compatibili (`.mp4`, `.mov`, `.m4v`)
- creazione job
- probing base del video con `ffprobe` se disponibile
- generazione di una telemetria **mock** strutturata come quella che servirà al frontend overlay
- endpoint preview per leggere i dati a un certo timestamp
- render **reale** di un nuovo MP4 con overlay bruciato nel video tramite `ffmpeg`
- download del video renderizzato

## Stato attuale

Questa versione renderizza davvero il video finale, ma la telemetria usata per l'overlay è ancora **simulata**. Quindi il file `.mp4` in output è reale, mentre i dati GPS/velocità non arrivano ancora dal tuo file GoPro.

## Requisiti

- Python 3.11+
- `ffmpeg` installato e disponibile nel `PATH`
- consigliato: `ffprobe` installato nel sistema

Verifica rapida:

```bash
ffmpeg -version
ffprobe -version
```

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

### `GET /api/jobs/{jobId}/telemetry`
Restituisce il JSON normalizzato con `video` e `samples`.

### `GET /api/jobs/{jobId}/preview?t=12.5`
Restituisce il sample più vicino a quel tempo e le label overlay già pronte.

### `POST /api/jobs/{jobId}/render`
Genera davvero un file MP4 renderizzato con overlay.

Body esempio:

```json
{
  "theme": "minimal-dark",
  "units": "hybrid",
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

Risposta esempio:

```json
{
  "jobId": "job_xxx",
  "status": "done",
  "message": "Render completato.",
  "telemetryMode": "mock",
  "renderedVideoUrl": "/files/jobs/job_xxx.rendered.mp4",
  "renderConfigUrl": "/files/jobs/job_xxx.render-config.json",
  "renderManifestUrl": "/files/jobs/job_xxx.render.json"
}
```

### `GET /api/jobs/{jobId}/artifacts`
Restituisce gli URL dei file generati:

- `telemetryUrl`
- `renderedVideoUrl`
- `renderConfigUrl`

## Come provarlo

1. Carica un video da `/docs` oppure dal frontend.
2. Prendi il `jobId`.
3. Chiama `POST /api/jobs/{jobId}/render`.
4. Apri `renderedVideoUrl` nel browser oppure scaricalo direttamente.

## Nota importante

Il render è sincrono: la richiesta `POST /render` resta aperta fino alla fine dell'encoding. Va bene per una MVP locale, ma per video lunghi conviene spostarlo in un worker asincrono.

## Prossimo step consigliato

1. Sostituire `generate_mock_telemetry()` con parser reale GoPro.
2. Aggiungere worker e coda per render asincrono.
3. Aggiungere mini-mappa reale come asset grafico o overlay video.
