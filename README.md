# Hong Kong Traffic Signs and Road Markings

Browse Hong Kong traffic signs and road markings, or explore surveyed traffic signs on a map. The public site is ready to use. A separate Docker version adds an assistant to the map.

## Use the public site

**[Open the gallery](https://lecberg.github.io/hk-tpdm-traffic-signs-markings/)** to browse 1,327 drawings. Search by code, filter signs and road markings, and download files as SVG or DXF. SVG is an image format. DXF is a drawing format used by design software.

**[Open the map](https://lecberg.github.io/hk-tpdm-traffic-signs-markings/map.html)** to explore about 157,000 surveyed traffic sign locations. Zoom in to see sign faces. Select a sign to view its code and available downloads.

The public site needs no installation or API key. It does not include the assistant.

## Run the Docker version with the assistant

The Docker version runs on your computer. It has the same Gallery and Map sections. The **Assistant** button appears only in the Map section.

The assistant has four tabs:

- **Signs:** Find drawings by code or available description.
- **Map:** Find a place and count nearby surveyed signs.
- **Convert:** Turn an SVG file into a DXF file.
- **Chat:** Ask a connected AI model about signs and map results.

Signs, Map, and Convert work without an AI key. Chat needs a supported model service.

### Start it

1. Install Docker Desktop or another Docker engine with Compose.
2. Copy `.env.example` to `.env`.
3. Run:

   ```sh
   docker compose up --build -d
   ```

4. Open **http://localhost:8517**.

Stop the site with `docker compose down`.

### Set up chat

In `.env`, choose one provider with `AI_PROVIDER`. Add that provider’s key and model. The available choices are `openai`, `deepseek`, `vercel`, and `custom`.

For example:

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-key
```

For another service that accepts OpenAI-style chat requests, choose `custom`. Set `CUSTOM_API_BASE_URL`, `CUSTOM_MODEL`, and `CUSTOM_API_KEY`. The model must support tool calls so it can request sign and map data.

After changing `.env`, run:

```sh
docker compose up -d --force-recreate backend
```

Then refresh the page. Keep `.env` private; Git ignores it.

Chat messages and selected search results go to the chosen model service. SVG files used for conversion stay in the local Docker service. Map tiles require internet access.

## About the data

The drawings follow Hong Kong traffic sign and road marking standards. Map locations come from the Transport Department’s [Traffic Aids Drawings open data](https://data.gov.hk/en-data/dataset/hk-td-tis_16-traffic-aids-drawings-v2). Some surveyed signs may have no matching drawing available for download.

## Convert your own files without Docker

The project also includes a small SVG-to-DXF converter:

```sh
pip install -e .
svg2dxf sign.svg
```

The command writes `sign.dxf` beside the source file.
