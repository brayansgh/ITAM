"""Ayudas de fixtures; no se utilizan en flujos de producción."""
def complete_decommission(asset, user=None):
    from accounts.models import User
    from maintenance.models import MaintenanceRecord, MaintenanceType, MaintenanceStatus
    ticket = MaintenanceRecord.objects.create(
        asset=asset, reported_by=user or User.objects.first(), type=MaintenanceType.DECOMMISSION,
        status=MaintenanceStatus.COMPLETED, description="Baja de prueba",
        resolution_notes="Disposición documentada con datos sintéticos.",
    )
    asset.refresh_from_db()
    return ticket
