from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
mail = Mail()

# Rate limiter se inicializa en app.py con setup_rate_limiter()
# Proxy object que evita AttributeError si se usa antes de inicializar
class _LimiterProxy:
    """Proxy para flask-limiter que no falla si no está inicializado."""
    _real = None

    def limit(self, *args, **kwargs):
        if self._real:
            return self._real.limit(*args, **kwargs)
        # Si no está inicializado, devuelve un decorador que no hace nada
        def noop_decorator(f):
            return f
        return noop_decorator

    def __getattr__(self, name):
        if self._real:
            return getattr(self._real, name)
        raise AttributeError(f"Limiter not initialized yet: {name}")

    def _set_real(self, real_limiter):
        self._real = real_limiter

limiter = _LimiterProxy()
