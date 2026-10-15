"""Uvicorn entry point: uvicorn apps.api.main:app --reload."""
from pumpguard.api.app import create_app
app=create_app()
