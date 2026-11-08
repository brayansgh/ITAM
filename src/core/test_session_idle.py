from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User


class AdminIdleSessionTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username="active_staff", is_staff=True))
        self.session_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.token_url = reverse("admin:itam_form_token")

    def set_expiry(self, expiry):
        Session.objects.filter(pk=self.session_key).update(expire_date=expiry)

    def test_admin_navigation_and_form_activity_renew_session(self):
        for url in (reverse("admin:index"), self.token_url):
            with self.subTest(url=url):
                now = timezone.now()
                self.set_expiry(now + timedelta(seconds=10))
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                expiry = Session.objects.get(pk=self.session_key).expire_date
                self.assertGreaterEqual(expiry, now + timedelta(minutes=5))

    def test_activity_after_expiry_cannot_reactivate_session(self):
        expired = timezone.now() - timedelta(seconds=1)
        self.set_expiry(expired)
        response = self.client.get(self.token_url)
        self.assertRedirects(
            response, reverse("admin:login") + f"?next={self.token_url}", fetch_redirect_response=False,
        )
        self.assertEqual(Session.objects.get(pk=self.session_key).expire_date, expired)
