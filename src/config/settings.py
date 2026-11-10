import os
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# Leer variables de entorno inyectadas por Docker
env = environ.Env(
    DJANGO_DEBUG=(bool, False)
)

SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env('DJANGO_DEBUG')
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=[])

INSTALLED_APPS = [
    'simple_history',
    'maintenance.apps.MaintenanceConfig',
    'core.admin_site.ITAMAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'accounts',
    'organizations',
    'inventory',
    'employees',
    'data_imports',
    'assignments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DATABASE_NAME'),
        'USER': env('DATABASE_USER'),
        'PASSWORD': env('DATABASE_PASSWORD'),
        'HOST': env('DATABASE_HOST'),
        'PORT': env('DATABASE_PORT'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'es-co'
TIME_ZONE = env('TIME_ZONE', default='America/Bogota')
USE_I18N = True
USE_TZ = True

# Rutas para archivos estáticos y media
STATIC_URL = 'static/'
STATIC_ROOT = Path(env('DJANGO_STATIC_ROOT', default=str(BASE_DIR / 'static')))
if STATIC_ROOT != BASE_DIR / 'static':
    STATICFILES_DIRS = [
        (directory, BASE_DIR / 'static' / directory)
        for directory in ('img', 'itam', 'js')
    ]


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.User'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# --- POLÍTICAS DE SEGURIDAD ISO 27001 ---
# Cinco minutos desde la última actividad.
SESSION_COOKIE_AGE = 300
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Protección contra robo de sesiones (XSS)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Activar únicamente cuando Nginx termine TLS y sobrescriba X-Forwarded-Proto.
if env.bool('DJANGO_HTTPS', default=False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int('DJANGO_HSTS_SECONDS', default=0)

# Recuperación de contraseña por correo corporativo.
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=not EMAIL_USE_SSL)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='')
ITAM_PASSWORD_RESET_ENABLED = bool(EMAIL_HOST and DEFAULT_FROM_EMAIL)
PASSWORD_RESET_TIMEOUT = 3600
