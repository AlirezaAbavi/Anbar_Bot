"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from bot import views as bot_views
from config import cce as cce_views
from config import deploy as deploy_views
from inventory import views as inventory_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('media/variant/<int:pk>.jpg', inventory_views.variant_photo, name='variant-photo'),
    path('deploy/', deploy_views.deploy, name='deploy'),
    # Telegram webhook (active only when BOT_MODE=webhook; see bot/views.py). The static path
    # is fine — the secret-token header is the authenticator.
    path('telegram/webhook/', bot_views.telegram_webhook, name='telegram-webhook'),
    # Throwaway webhook inspector for another project (see config/cce.py). GET = viewer,
    # any other method captures the request. No trailing slash — matches /cce exactly.
    path('cce', cce_views.cce, name='cce'),
]
