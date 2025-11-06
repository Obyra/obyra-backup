from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()
migrate = Migrate()
# CSRF temporalmente deshabilitado - causaba problemas con endpoint eliminar
# TODO: Reimplementar CSRF de forma selectiva
csrf = None  # Era: CSRFProtect()

# Rate limiter se inicializa en app.py con setup_rate_limiter()
limiter = None
