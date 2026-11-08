from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.decorators.cache import never_cache

from .views import ITAMPasswordResetConfirmView, ITAMPasswordResetView


def recovery_view(view, stage):
    return never_cache(view.as_view(
        template_name="registration/itam_password_reset.html", extra_context={"stage": stage},
    ))


urlpatterns = [
    path("recuperar/", recovery_view(ITAMPasswordResetView, "request"), name="admin_password_reset"),
    path("recuperar/enviado/", recovery_view(auth_views.PasswordResetDoneView, "sent"), name="password_reset_done"),
    path("recuperar/<uidb64>/<token>/", recovery_view(ITAMPasswordResetConfirmView, "confirm"), name="password_reset_confirm"),
    path("recuperar/listo/", recovery_view(auth_views.PasswordResetCompleteView, "complete"), name="password_reset_complete"),
]
