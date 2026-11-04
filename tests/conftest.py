# tests/conftest.py — put the project root on sys.path so `pytest tests/ -q`
# can import the top-level modules (consistency_lint, publish_close,
# publish_public_site_lib) without each test file needing its own hack.
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True          # no __pycache__ in the Drive folder (Google Drive syncs every file)
