from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class LandingTests(TestCase):
    def test_anonymous_visitor_sees_login_and_admin_stays_protected(self):
        login_url = reverse("admin:login")
        admin_url = reverse("admin:index")
        destination = f"{login_url}?next={admin_url}"
        response = self.client.get(reverse("itam_landing"))
        self.assertContains(response, f'href="{destination}"')
        self.assertContains(response, 'id="itam-theme"')
        self.assertContains(response, 'role="switch" aria-label="Tema oscuro"')
        self.assertIn("no-store", response["Cache-Control"])
        self.assertRedirects(self.client.get(admin_url), destination, fetch_redirect_response=False)

    def test_staff_with_session_can_go_to_dashboard(self):
        self.client.force_login(User.objects.create_user(username="landing_staff", is_staff=True))
        response = self.client.get(reverse("itam_landing"))
        self.assertContains(response, f'href="{reverse("admin:index")}"')
        self.assertContains(response, "Ir al panel")
        self.assertNotContains(response, "Iniciar sesión")

    def test_authenticated_user_without_staff_permission_sees_login(self):
        self.client.force_login(User.objects.create_user(username="landing_non_staff"))
        response = self.client.get(reverse("itam_landing"))
        self.assertContains(response, "Iniciar sesión")
        self.assertNotContains(response, "Ir al panel")

    def test_login_and_dashboard_use_same_theme_picker_as_landing(self):
        login = self.client.get(reverse("admin:login"))
        self.assertContains(login, "itam/theme.js")
        self.assertContains(login, 'id="itam-theme"', count=1)
        self.assertContains(login, 'class="itam-login-theme"')
        self.client.force_login(User.objects.create_user(username="theme_staff", is_staff=True))
        dashboard = self.client.get(reverse("admin:index"))
        self.assertContains(dashboard, "itam/theme.js")
        self.assertContains(dashboard, 'id="itam-theme"', count=1)
        self.assertNotContains(dashboard, 'class="itam-login-theme"')

    def test_login_keeps_form_errors_and_redirects_after_authentication(self):
        user = User.objects.create_user(username="login_staff", password="Example-4826!", is_staff=True)
        target = reverse("admin:inventory_asset_changelist")
        url = f'{reverse("admin:login")}?next={target}'
        failed = self.client.post(url, {"username": user.username, "password": "incorrect", "next": target})
        self.assertContains(failed, "Iniciar sesión")
        self.assertContains(failed, 'class="errornote"')
        self.assertContains(failed, f'name="next" value="{target}"')
        accepted = self.client.post(url, {"username": user.username, "password": "Example-4826!", "next": target})
        self.assertRedirects(accepted, target, fetch_redirect_response=False)

    def test_logout_closes_session_and_shows_itam_confirmation(self):
        self.client.force_login(User.objects.create_user(username="logout_staff", is_staff=True))
        logout_url = reverse("admin:logout")
        self.assertEqual(self.client.get(logout_url).status_code, 405)
        response = self.client.post(logout_url)
        self.assertContains(response, "Sesión cerrada")
        self.assertContains(response, "Volver a iniciar sesión")
        self.assertContains(response, 'id="itam-theme"', count=1)
        self.assertNotContains(response, "Gracias por pasar un buen rato con el sitio web hoy.")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(
            self.client.get(reverse("admin:index")), f'{reverse("admin:login")}?next={reverse("admin:index")}',
            fetch_redirect_response=False,
        )
