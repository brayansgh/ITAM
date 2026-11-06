from django.contrib import admin
from django.urls import path
from assignments.views import download_act_pdf

urlpatterns = [
    path('admin/', admin.site.urls),
    # CORRECCIÓN: Se cambia <int:...> por <uuid:...> para aceptar el formato de seguridad de la base de datos
    path('actas/<uuid:assignment_id>/descargar/', download_act_pdf, name='download_act_pdf'),
]
