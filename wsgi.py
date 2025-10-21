"""WSGI entrypoint for the OBYRA application."""
from app import create_app

app = create_app()
