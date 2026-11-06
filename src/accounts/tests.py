from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from .models import Role, User


class AccountAdminTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="account_admin", password="Admin-test-4826!", email="admin@example.test",
        )
        self.target = User.objects.create_user(username="account_target", password="Target-test-4826!")
        self.group = Group.objects.create(name="Grupo de prueba")
        self.permission = Permission.objects.get(
            content_type__app_label="inventory", codename="view_asset",
        )
        self.client.force_login(self.operator)
        self.change_url = reverse("admin:accounts_user_change", args=[self.target.pk])
        self.history_url = reverse("admin:accounts_user_history", args=[self.target.pk])

    def change_data(self, **overrides):
        data = {
            "username": self.target.username, "first_name": "", "last_name": "",
            "email": "", "role": Role.CONSULTATION, "is_active": "on",
            "groups": [], "user_permissions": [], "_save": "Guardar",
        }
        data.update(overrides)
        return data

    def test_change_page_hides_hash_metadata_and_exposes_role(self):
        response = self.client.get(self.change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contraseña configurada")
        self.assertContains(response, 'name="role"')
        self.assertNotContains(response, "pbkdf2_sha256")
        self.assertNotContains(response, self.target.password)
        self.assertContains(response, f"../../{self.target.pk}/password/")

    def test_password_submission_cannot_overwrite_hash(self):
        previous = self.target.password
        response = self.client.post(self.change_url, self.change_data(password="tampered"))
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, previous)

    def test_profile_history_displays_actor_and_role_without_timestamp_noise(self):
        response = self.client.post(self.change_url, self.change_data(role=Role.TECHNOLOGY))
        self.assertEqual(response.status_code, 302)
        record = self.target.history.first()
        self.assertEqual(record.history_user, self.operator)
        self.assertEqual(record.role, Role.TECHNOLOGY)
        response = self.client.get(self.history_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rol ITAM")
        self.assertContains(response, "Tecnología")
        self.assertContains(response, self.operator.username)
        self.assertNotContains(response, "updated_at")
        self.assertNotContains(response, "No hay versiones registradas.")

    def test_group_and_permission_changes_are_audited(self):
        response = self.client.post(self.change_url, self.change_data(
            groups=[self.group.pk], user_permissions=[self.permission.pk],
        ))
        self.assertEqual(response.status_code, 302)
        entry = LogEntry.objects.filter(object_id=str(self.target.pk)).latest("pk")
        self.assertEqual(entry.user, self.operator)
        self.assertIn("Grupos: Sin asignar → Grupo de prueba", entry.get_change_message())
        self.assertIn("Permisos individuales: Sin asignar →", entry.get_change_message())
        self.assertTrue(self.target.groups.filter(pk=self.group.pk).exists())
        response = self.client.get(self.history_url)
        self.assertContains(response, "Grupos: Sin asignar → Grupo de prueba")
        response = self.client.post(self.change_url, self.change_data())
        self.assertEqual(response.status_code, 302)
        entry = LogEntry.objects.filter(object_id=str(self.target.pk)).latest("pk")
        self.assertIn("Grupos: Grupo de prueba → Sin asignar", entry.get_change_message())

    def test_group_permission_changes_have_before_and_after(self):
        url = reverse("admin:auth_group_change", args=[self.group.pk])
        response = self.client.post(url, {"name": self.group.name, "permissions": [self.permission.pk]})
        self.assertEqual(response.status_code, 302)
        entry = LogEntry.objects.filter(
            content_type__app_label="auth", content_type__model="group", object_id=str(self.group.pk),
        ).latest("pk")
        self.assertIn("Permisos del grupo: Sin asignar →", entry.get_change_message())

    def test_password_change_remains_available_and_is_masked_in_history(self):
        response = self.client.post(
            reverse("admin:auth_user_password_change", args=[self.target.pk]),
            {"password1": "Replacement-test-4826!", "password2": "Replacement-test-4826!"},
        )
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("Replacement-test-4826!"))
        response = self.client.get(self.history_url)
        self.assertContains(response, "Contraseña")
        self.assertContains(response, "*** Modificada")
        self.assertNotContains(response, self.target.password)
        self.assertNotContains(response, "pbkdf2_sha256")

    def test_unauthorized_staff_cannot_access_profile_or_history(self):
        user = User.objects.create_user(username="no_user_permissions", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.change_url).status_code, 403)
        self.assertEqual(self.client.get(self.history_url).status_code, 403)

    def test_add_user_page_offers_role_and_groups(self):
        response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'name="groups"')

    def test_view_only_user_cannot_see_password_hash(self):
        viewer = User.objects.create_user(username="account_viewer", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_user",
        ))
        self.client.force_login(viewer)
        response = self.client.get(self.change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contraseña configurada")
        self.assertNotContains(response, self.target.password)
        self.assertNotContains(response, "pbkdf2_sha256")
