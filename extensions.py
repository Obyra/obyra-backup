"""
Flask extensions initialization
This module contains Flask extension instances to avoid circular imports
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Initialize extensions
migrate = Migrate()
db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()

