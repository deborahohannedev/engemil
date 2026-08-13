from config.settings.base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Em dev, libera qualquer origem para o frontend rodar em outra porta
# sem friccao. NUNCA usar isso em producao.
CORS_ALLOW_ALL_ORIGINS = True