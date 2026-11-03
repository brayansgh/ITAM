from django.contrib import admin
from .models import Employee

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'document_number', 'company', 'site', 'area', 'status')
    list_filter = ('status', 'company', 'site', 'area')
    search_fields = ('full_name', 'document_number', 'email')
