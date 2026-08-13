from config.settings.base import *  # noqa: F401, F403
from config.settings.base import env

DEBUG = False

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS')
CORS_ALLOWED_ORIGINS = env.list('DJANGO_CORS_ALLOWED_ORIGINS')

# WhiteNoise precisa estar logo depois do SecurityMiddleware
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

SECURE_CONTENT_TYPE_NOSNIFF = True


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}