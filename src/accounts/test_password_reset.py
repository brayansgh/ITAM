import re
from urllib.parse import urlsplit

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import User


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ITAM_PASSWORD_RESET_ENABLED=True,
)
class PasswordRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(
            username="reset_staff", email="staff@example.test",
            password="Before-reset-4826!", is_staff=True,
        )
        self.request_url = reverse("admin_password_reset")
        self.sent_url = reverse("password_reset_done")

    def request_link(self, email):
        response = self.client.post(self.request_url, {"email": email})
        self.assertRedirects(response, self.sent_url)
        return response

    def test_login_offers_recovery_and_password_visibility_control(self):
        response = self.client.get(reverse("admin:login"))
        self.assertContains(response, f'href="{self.request_url}"')
        self.assertContains(response, "¿Olvidaste tu contraseña?")
        self.assertContains(response, 'aria-controls="id_password"')
        self.assertContains(response, 'type="password"')

    def test_registered_user_can_set_a_password_only_once(self):
        self.request_link(self.user.email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        link = urlsplit(re.search(r"https?://\S+", mail.outbox[0].body).group()).path
        redirect = self.client.get(link)
        self.assertEqual(redirect.status_code, 302)
        self.assertIn("/set-password/", redirect.url)
        self.assertContains(self.client.get(redirect.url), "Establecer nueva contraseña")
        self.assertRedirects(self.client.post(redirect.url, {
            "new_password1": "After-reset-2746!", "new_password2": "After-reset-2746!",
        }), reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("After-reset-2746!"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.get(link), "Enlace no válido")

    def test_unknown_nonstaff_or_shared_email_has_same_confirmation(self):
        User.objects.create_user(username="reset_nonstaff", email="nonstaff@example.test", password="Synthetic-4826!")
        User.objects.create_user(username="reset_shared", email=self.user.email, password="Synthetic-4826!", is_staff=True)
        for email in ("unknown@example.test", "nonstaff@example.test", self.user.email):
            with self.subTest(email=email):
                self.request_link(email)
        self.assertEqual(len(mail.outbox), 0)

    def test_repeat_request_is_throttled(self):
        self.request_link(self.user.email)
        self.request_link(self.user.email.upper())
        self.assertEqual(len(mail.outbox), 1)

    def test_recovery_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post(self.request_url, {"email": self.user.email})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(ITAM_PASSWORD_RESET_ENABLED=False)
    def test_unconfigured_recovery_explains_how_to_get_help(self):
        self.assertContains(self.client.get(self.request_url), "La recuperación por correo aún no está disponible")
        self.assertContains(self.client.post(self.request_url, {"email": self.user.email}), "Dirección de Tecnología")
        self.assertEqual(len(mail.outbox), 0)
