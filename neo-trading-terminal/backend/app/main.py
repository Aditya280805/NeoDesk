from app.core.config import settings
from app.terminal.server import create_app

app = create_app(settings)
