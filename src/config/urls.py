from django.contrib import admin
from django.urls import include, path
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView
from assignments.views import download_act_pdf

urlpatterns = [
    path("", never_cache(TemplateView.as_view(template_name="itam_landing.html")), name="itam_landing"),
    path('admin/', admin.site.urls),
    path("cuenta/", include("accounts.urls")),
    # CORRECCIÓN: Se cambia <int:...> por <uuid:...> para aceptar el formato de seguridad de la base de datos
    path('actas/<uuid:assignment_id>/descargar/', download_act_pdf, name='download_act_pdf'),
]
