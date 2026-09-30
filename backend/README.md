# Confiance backend

FastAPI service behind the Confiance web app. Python 3.13, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                              # install
uv run uvicorn confiance.api.app:app --port 8000     # run (serves frontend/dist too when it is built)
uv run pytest                                        # 154 tests, no network or keys
```

See the [project README](../README.md) for the product overview and one-command setup (`./run.sh`),
[docs/architecture.md](../docs/architecture.md) for the module map and
[docs/configuration.md](../docs/configuration.md) for settings.
