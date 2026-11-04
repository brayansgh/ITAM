from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from assignments.views import download_act_pdf

urlpatterns = [
    path('admin/', admin.site.urls),
    # CORRECCIÓN: Se cambia <int:...> por <uuid:...> para aceptar el formato de seguridad de la base de datos
    path('actas/<uuid:assignment_id>/descargar/', download_act_pdf, name='download_act_pdf'),
]


urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
