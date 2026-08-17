# Makes `backend` an importable package so the import-linter contract
# (bridge-ui/backend/pyproject.toml, root_packages=["backend"]) can resolve the
# module graph. The app's dual-import shim already supports package mode
# (`from backend.core... import ...`); flat mode (`uvicorn server:app` from this
# dir) is unaffected by the presence of this file.
