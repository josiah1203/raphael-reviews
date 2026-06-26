# raphael-reviews

Review requests, gates, threads, merge workflows

## API

- Prefix: `/v1/reviews`
- Port: `8087`
- Health: `GET /health`

## Events

_Published and consumed events documented in `openapi.yaml` and raphael-contracts._

## Development

```bash
uv sync
uv run uvicorn raphael_reviews.app:app --reload --port 8087
```

Part of the [Raphael Platform](https://github.com/hummingbird-labs) by HummingBird Labs.
