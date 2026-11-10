"""Admin corporativo: conserva ModelAdmin como autoridad de permisos y flujos."""
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import TruncMonth
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.http import urlencode


class ITAMAdminConfig(AdminConfig):
    default_site = 'core.admin_site.ITAMAdminSite'


class ITAMAdminSite(AdminSite):
    site_header = 'ACEPALMA ITAM'
    site_title = 'ACEPALMA ITAM'
    index_title = 'Dashboard'
    site_url = None

    def get_urls(self):
        return [
            path('token-formulario/', self.admin_view(self.form_token), name='itam_form_token'),
            path('buscar/', self.admin_view(self.search), name='itam_search'),
            path('documentos/', self.admin_view(self.documents), name='itam_documents'),
            path('bajas/nueva/', self.admin_view(self.decommission_add), name='maintenance_decommission_add'),
            path('bajas/<uuid:object_id>/', self.admin_view(self.decommission_change), name='maintenance_decommission_change'),
            path('bajas/', self.admin_view(self.decommissions), name='itam_decommissions'),
            path('auditoria/', self.admin_view(self.audit_catalog), name='itam_audit'),
        ] + super().get_urls()

    def form_token(self, request):
        from django.http import JsonResponse, HttpResponseNotAllowed
        from django.middleware.csrf import get_token
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
        return JsonResponse({'csrfToken': get_token(request)})

    def visible_queryset(self, request, model):
        model_admin = self._registry[model]
        if not (model_admin.has_module_permission(request) and model_admin.has_view_permission(request)):
            return model_admin.get_queryset(request).none()
        return model_admin.get_queryset(request)

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        labels = {
            "accounts": "Administración",
            "assignments": "Movimientos",
            "data_imports": "Importaciones",
            "employees": "Personas",
            "organizations": "Organización",
        }
        for app in apps:
            app["name"] = labels.get(app["app_label"], app["name"])
        return sorted(apps, key=lambda app: app["name"].lower())

    def each_context(self, request):
        context = super().each_context(request)
        groups = [
            ('Gestión de activos', [('inventory.asset', 'Inventario de activos'), ('inventory.category', 'Tipos de activo'), ('inventory.brand', 'Marcas'), ('inventory.modelasset', 'Modelos')]),
            ('Movimientos', [('assignments.assignment', 'Historial de asignaciones'), ('assignments.employeeassetsummary', 'Resumen por usuarios'), ('maintenance.maintenancerecord', 'Mantenimiento')]),
            ('Personas', [('employees.employee', 'Empleados'), ('employees.retiredemployee', 'Empleados retirados')]),
            ('Organización', [('organizations.company', 'Compañías'), ('organizations.site', 'Ubicaciones físicas'), ('organizations.area', 'Áreas')]),
            ('Administración', [('accounts.user', 'Usuarios y permisos'), ('auth.group', 'Grupos'), ('data_imports.stagingasset', 'Importaciones')]),
        ]
        available = {f"{app['app_label']}.{m['object_name'].lower()}": m for app in context['available_apps'] for m in app['models']}
        icons = {'inventory.asset': '💻', 'inventory.category': '🗂️', 'inventory.brand': '🏷️', 'inventory.modelasset': '🖥️', 'assignments.assignment': '🔄', 'assignments.employeeassetsummary': '👥', 'maintenance.maintenancerecord': '🔧', 'employees.employee': '👤', 'employees.retiredemployee': '👥', 'organizations.company': '🏢', 'organizations.site': '📍', 'organizations.area': '🏬', 'accounts.user': '🔐', 'auth.group': '👥', 'data_imports.stagingasset': '📥'}
        menu = []
        for label, models in groups:
            links = [{'label': title, 'icon': icons[key], 'url': available[key]['admin_url']} for key, title in models
                     if key in available and available[key].get('admin_url')]
            if label == 'Movimientos' and ('maintenance.maintenancerecord' in available or 'inventory.decommissionedasset' in available):
                links.append({'label': 'Bajas', 'icon': '🗑️', 'url': reverse('admin:itam_decommissions')})
            if label == 'Administración' and available:
                links.append({'label': 'Auditoría', 'icon': '📋', 'url': reverse('admin:itam_audit')})
            if links:
                menu.append({'label': label, 'links': links})
        if any(k in available for k in ('assignments.assignment', 'assignments.offboardingrecord', 'maintenance.maintenancerecord')):
            menu.insert(min(3, len(menu)), {'label': 'Documentación', 'links': [{'label': 'Documentos y actas', 'icon': '📄', 'url': reverse('admin:itam_documents')}]})
        model_labels = {key: title for _, models in groups for key, title in models}
        model_labels["inventory.decommissionedasset"] = "Bajas"
        context.update(itam_menu=menu, itam_model_labels=model_labels, itam_now=timezone.now())
        return context

    def page(self, request, template, title, **context):
        request.current_app = self.name
        return TemplateResponse(request, template, {**self.each_context(request), 'title': title, **context})

    def index(self, request, extra_context=None):
        from inventory.models import Asset, AssetStatus
        from assignments.models import Assignment
        from maintenance.models import MaintenanceRecord, MaintenanceStatus, MaintenanceType
        from employees.models import Employee
        assets = self.visible_queryset(request, Asset)
        assignments = self.visible_queryset(request, Assignment)
        tickets = self.visible_queryset(request, MaintenanceRecord)
        counts = dict(assets.values('status').annotate(n=Count('pk')).values_list('status', 'n'))
        base = reverse('admin:inventory_asset_changelist')
        metrics = [{'label': 'Activos registrados', 'value': sum(counts.values()), 'url': base, 'icon': '💻'}]
        for status, label, icon in [(AssetStatus.ASSIGNED, 'Estado asignado', '✅'), (AssetStatus.AVAILABLE, 'Disponibles', '📦'), (AssetStatus.IN_MAINTENANCE, 'En mantenimiento', '🔧'), (AssetStatus.DECOMMISSIONED, 'Dados de baja', '🗑️')]:
            target = reverse('admin:inventory_decommissionedasset_changelist') if status == AssetStatus.DECOMMISSIONED else base + '?' + urlencode({'status__exact': status})
            metrics.append({'label': label, 'value': counts.get(status, 0), 'url': target, 'icon': icon})
        asset_admin = self._registry[Asset]
        if not asset_admin.has_view_permission(request):
            metrics = []
        # Inventario excluye bajas en su listado, por lo que se suman solo si hay permiso.
        from inventory.models import DecommissionedAsset
        decommissioned = self.visible_queryset(request, DecommissionedAsset).count()
        if metrics:
            metrics[0]['value'] += decommissioned
            metrics[-1]['value'] = decommissioned
        category_rows = list(assets.values('category__group').annotate(n=Count('pk')).order_by('-n'))
        from inventory.models import AssetGroup
        labels = dict(AssetGroup.choices)
        total = sum(r['n'] for r in category_rows) or 1
        for row in category_rows:
            row.update(label=labels.get(row['category__group'], 'Sin grupo (legado)'), percent=round(row['n'] * 100 / total))
        palette = {'COMPUTING': '#477c98', 'PERIPHERALS': '#78a3b9', 'NETWORK': '#f37035', 'TELEPHONY': '#ace1fa', 'OTHER': '#8b9ba5', '': '#c3ccd2'}
        stops = []
        cursor = 0
        for row in category_rows:
            row['color'] = palette.get(row['category__group'], '#c3ccd2')
            end = cursor + row['n'] * 100 / total
            stops.append(f"{row['color']} {cursor:.3f}% {end:.3f}%")
            cursor = end
        category_gradient = ', '.join(stops) or '#edf3f7 0% 100%'
        companies = list(assets.values('company__name').annotate(n=Count('pk')).order_by('-n')[:10])
        largest = max((row['n'] for row in companies), default=1)
        for row in companies:
            row['percent'] = round(row['n'] * 100 / largest)
        now = timezone.localtime()
        months = []
        for offset in reversed(range(6)):
            number = now.year * 12 + now.month - 1 - offset
            months.append(timezone.datetime(number // 12, number % 12 + 1, 1, tzinfo=now.tzinfo))
        series = []
        for field in ('assigned_at', 'returned_at'):
            series.append({row['month'].strftime('%Y-%m'): row['n'] for row in assignments.filter(**{field + '__gte': months[0]}).annotate(month=TruncMonth(field)).values('month').annotate(n=Count('pk'))})
        activity = [{'label': month.strftime('%m/%Y'), 'assigned': series[0].get(month.strftime('%Y-%m'), 0), 'returned': series[1].get(month.strftime('%Y-%m'), 0)} for month in months]
        maximum = max((max(row['assigned'], row['returned']) for row in activity), default=1) or 1
        for row in activity:
            row.update(assigned_height=round(row['assigned'] * 100 / maximum), returned_height=round(row['returned'] * 100 / maximum))
        recent = []
        aa = self._registry[Assignment]
        for field, label in [('assigned_at', 'Asignación'), ('returned_at', 'Devolución')]:
            for obj in assignments.filter(**{field + '__isnull': False}).select_related('asset', 'employee', 'assigned_by').order_by('-' + field)[:6]:
                if aa.has_view_permission(request, obj):
                    recent.append({'date': getattr(obj, field), 'label': label, 'asset': obj.asset.display_identifier, 'person': obj.employee.full_name, 'actor': str(obj.assigned_by) if field == 'assigned_at' else 'Consultar registro', 'url': reverse('admin:assignments_assignment_change', args=[obj.pk])})
        ta = self._registry[MaintenanceRecord]
        for obj in tickets.select_related('asset', 'reported_by').order_by('-created_at')[:6]:
            if ta.has_view_permission(request, obj):
                recent.append({'date': obj.created_at, 'label': 'Trámite de baja' if obj.type == MaintenanceType.DECOMMISSION else 'Registro de ticket', 'asset': obj.asset.display_identifier, 'person': '—', 'actor': str(obj.reported_by), 'url': reverse('admin:maintenance_maintenancerecord_change', args=[obj.pk])})
        recent.sort(key=lambda row: row['date'], reverse=True)
        alerts = []
        employees = self.visible_queryset(request, Employee)
        if aa.has_view_permission(request) and self._registry[Employee].has_view_permission(request):
            count = assignments.filter(status='ACTIVE', employee__in=employees.filter(status='RETIRO')).values('employee_id').distinct().count()
            if count:
                alerts.append({'count': count, 'label': 'Empleados retirados con custodia vigente', 'url': reverse('admin:employees_employee_changelist') + '?status__exact=RETIRO'})
        count = tickets.filter(status__in=(MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS)).exclude(type=MaintenanceType.DECOMMISSION).count()
        if count:
            alerts.append({'count': count, 'label': 'Tickets técnicos abiertos o en proceso', 'url': reverse('admin:maintenance_maintenancerecord_changelist')})
        return self.page(request, 'admin/itam/dashboard.html', 'Dashboard', metrics=metrics, categories=category_rows, category_gradient=category_gradient, category_total=sum(row['n'] for row in category_rows), companies=companies, activity=activity, recent=recent[:8], alerts=alerts, **(extra_context or {}))

    def search(self, request):
        from inventory.models import Asset, DecommissionedAsset
        from employees.models import Employee, RetiredEmployee
        term = request.GET.get('q', '').strip()[:150]
        results = []
        for label, action, models in (
            ('Activos', 'Ver activo', (Asset, DecommissionedAsset)),
            ('Empleados', 'Ver empleado', (Employee, RetiredEmployee)),
        ):
            rows = []
            if term:
                for model in models:
                    ma = self._registry[model]
                    qs, duplicates = ma.get_search_results(request, self.visible_queryset(request, model), term)
                    if duplicates:
                        qs = qs.distinct()
                    for obj in qs[:20]:
                        if ma.has_view_permission(request, obj):
                            rows.append({
                                'label': str(obj),
                                'status': obj.get_status_display(),
                                'url': reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_change', args=[obj.pk]),
                            })
            results.append({'label': label, 'action': action, 'rows': rows})
        return self.page(request, 'admin/itam/search.html', 'Resultados de búsqueda', query=term, results=results)

    def documents(self, request):
        from assignments.models import Assignment, OffboardingRecord
        from maintenance.models import MaintenanceDocument, MaintenanceRecord, MaintenanceType
        kind = request.GET.get('tipo', 'entrega')
        if kind not in ('entrega', 'devolucion', 'desvinculacion', 'mantenimiento', 'baja'):
            kind = 'entrega'
        config = {'entrega': (Assignment, 'signed_act_pdf'), 'devolucion': (OffboardingRecord, 'pdf'), 'desvinculacion': (OffboardingRecord, 'pdf'), 'mantenimiento': (MaintenanceRecord, None), 'baja': (MaintenanceRecord, None)}
        model, field = config[kind]
        ma = self._registry[model]
        if not ma.has_view_permission(request) or not ma.has_module_permission(request):
            # Seleccionar la primera sección autorizada cuando no se pidió una en concreto.
            if 'tipo' not in request.GET:
                from django.shortcuts import redirect
                for key, (candidate, _) in config.items():
                    target = self._registry[candidate]
                    if target.has_view_permission(request) and target.has_module_permission(request):
                        return redirect(reverse('admin:itam_documents') + '?tipo=' + key)
            raise PermissionDenied
        qs = self.visible_queryset(request, model)
        if kind == 'devolucion':
            qs = qs.exclude(return_reason='')
        elif kind == 'desvinculacion':
            qs = qs.filter(return_reason='')
        if field:
            qs = qs.exclude(**{field: ''}).exclude(**{field + '__isnull': True}).select_related(
                *(['asset', 'employee'] if kind == 'entrega' else ['employee'])
            ).order_by('-created_at')
        else:
            if kind == 'baja':
                qs = qs.filter(type=MaintenanceType.DECOMMISSION)
            else:
                qs = qs.exclude(type=MaintenanceType.DECOMMISSION)
            qs = MaintenanceDocument.objects.filter(maintenance__in=qs).select_related('maintenance__asset').order_by('-pk')
        from django.utils.dateparse import parse_date
        for param, lookup in [('desde', 'gte'), ('hasta', 'lte')]:
            try:
                date = parse_date(request.GET.get(param, ''))
            except ValueError:
                date = None
            if date:
                key = 'created_at' if field else 'maintenance__created_at'
                qs = qs.filter(**{key + '__date__' + lookup: date})
        page = Paginator(qs, 25).get_page(request.GET.get('page'))
        rows = []
        for obj in page:
            record = obj if field else obj.maintenance
            if not ma.has_view_permission(request, record):
                continue
            if kind == 'entrega':
                url, label = reverse('download_act_pdf', args=[obj.pk]), str(obj.asset)
            elif kind in ('devolucion', 'desvinculacion'):
                url, label = reverse('admin:assignments_offboardingrecord_view_pdf', args=[obj.pk]), str(obj.employee)
            else:
                url, label = reverse('admin:maintenance_document_download', args=[obj.pk]), str(obj.maintenance.asset)
            detail_url = (reverse('admin:assignments_offboardingrecord_receipt', args=[obj.pk])
                          if kind in ('devolucion', 'desvinculacion') else None)
            rows.append({'date': record.created_at, 'label': label, 'url': url, 'detail_url': detail_url,
                         'document_type': {'entrega': 'Entrega', 'devolucion': 'Devolución', 'desvinculacion': 'Desvinculación',
                                           'mantenimiento': 'Mantenimiento', 'baja': 'Baja'}[kind],
                         'employee': obj.employee.full_name if field else 'No aplica'})
        tabs = [{'label': label, 'url': '?tipo=' + key, 'active': key == kind} for key, label in [('entrega', 'Entrega'), ('devolucion', 'Devolución'), ('desvinculacion', 'Desvinculación'), ('mantenimiento', 'Mantenimiento'), ('baja', 'Bajas')] if self._registry[config[key][0]].has_view_permission(request) and self._registry[config[key][0]].has_module_permission(request)]
        return self.page(request, 'admin/itam/documents.html', 'Documentos y actas', rows=rows, tabs=tabs, page=page, kind=kind)

    def decommission_add(self, request):
        from maintenance.models import MaintenanceRecord
        return self._registry[MaintenanceRecord].add_view(request)

    def decommission_change(self, request, object_id):
        from maintenance.models import MaintenanceRecord
        return self._registry[MaintenanceRecord].decommission_change_view(request, object_id)

    def decommissions(self, request):
        from inventory.models import DecommissionedAsset
        from maintenance.models import MaintenanceRecord, MaintenanceType
        kind = request.GET.get('estado', 'tramite')
        if kind not in ('tramite', 'definitivas', 'cancelados'):
            kind = 'tramite'
        model = DecommissionedAsset if kind == 'definitivas' else MaintenanceRecord
        ma = self._registry[model]
        if not ma.has_view_permission(request) or not ma.has_module_permission(request):
            if 'estado' not in request.GET and self._registry[DecommissionedAsset].has_view_permission(request):
                from django.shortcuts import redirect
                return redirect(reverse('admin:itam_decommissions') + '?estado=definitivas')
            raise PermissionDenied
        qs = self.visible_queryset(request, model)
        if kind == 'definitivas':
            from inventory.models import Asset, AssetStatus

            versions = Asset.history.model.objects.using(qs.db)
            previous_status = versions.filter(id=OuterRef('id')).filter(
                Q(history_date__lt=OuterRef('history_date'))
                | Q(history_date=OuterRef('history_date'), history_id__lt=OuterRef('history_id'))
            ).order_by('-history_date', '-history_id').values('status')[:1]
            # Una primera versión que ya figura en baja no acredita una transición.
            transitions = versions.filter(
                id=OuterRef('pk'), status=AssetStatus.DECOMMISSIONED, history_type='~',
            ).annotate(previous_status=Subquery(previous_status)).filter(
                previous_status__isnull=False,
            ).exclude(previous_status=AssetStatus.DECOMMISSIONED)
            decommission_date = transitions.order_by('-history_date', '-history_id').values('history_date')[:1]
            qs = qs.annotate(display_date=Subquery(decommission_date))
        else:
            qs = qs.filter(type=MaintenanceType.DECOMMISSION, status__in=['CANCELLED'] if kind == 'cancelados' else ['OPEN', 'IN_PROGRESS'])
            qs = qs.annotate(display_date=F('created_at'))
        page = Paginator(qs.order_by(F('display_date').desc(nulls_last=True), '-pk'), 25).get_page(request.GET.get('page'))
        rows = []
        for obj in page:
            if ma.has_view_permission(request, obj):
                asset = obj if kind == 'definitivas' else obj.asset
                route = 'inventory_decommissionedasset' if kind == 'definitivas' else 'maintenance_decommission'
                rows.append({'asset': asset, 'status': obj.get_status_display(), 'date': obj.display_date, 'url': reverse('admin:' + route + '_change', args=[obj.pk])})
        can_create = self._registry[MaintenanceRecord].has_add_permission(request)
        tabs = [{'label': label, 'url': '?estado=' + key, 'active': kind == key} for key, label in [('tramite', 'En trámite'), ('definitivas', 'Bajas definitivas'), ('cancelados', 'Cancelados')] if self._registry[DecommissionedAsset if key == 'definitivas' else MaintenanceRecord].has_view_permission(request)]
        return self.page(request, 'admin/itam/decommissions.html', 'Bajas', tabs=tabs, rows=rows, page=page, kind=kind, can_create=can_create)

    def audit_catalog(self, request):
        links = []
        groups = []
        icons = {'inventory': '💻', 'assignments': '🔄', 'maintenance': '🔧',
                 'employees': '👥', 'organizations': '🏢', 'accounts': '🔐',
                 'auth': '🔐', 'data_imports': '📥'}
        for app in self.get_app_list(request):
            app_links = [{'label': model['name'], 'url': model['admin_url']}
                         for model in app['models'] if model.get('admin_url')]
            if app_links:
                groups.append({'label': app['name'], 'links': app_links,
                               'icon': icons.get(app['app_label'], '📋')})
                links.extend(app_links)
        return self.page(request, 'admin/itam/audit.html', 'Auditoría', links=links, audit_groups=groups)
