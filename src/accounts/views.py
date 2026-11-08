from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.utils.crypto import salted_hmac


class ITAMPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        users = [user for user in super().get_users(email) if user.is_staff]
        if len(users) == 1:
            yield users[0]


class ITAMPasswordResetView(auth_views.PasswordResetView):
    form_class = ITAMPasswordResetForm

    def get_context_data(self, **kwargs):
        return super().get_context_data(reset_enabled=settings.ITAM_PASSWORD_RESET_ENABLED, **kwargs)

    def form_valid(self, form):
        if not settings.ITAM_PASSWORD_RESET_ENABLED:
            return self.render_to_response(self.get_context_data(form=form))

        email = form.cleaned_data["email"].casefold()
        key = salted_hmac("itam-password-reset", email).hexdigest()
        if not cache.add(f"password-reset:{key}", True, timeout=60):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class ITAMPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user and user.is_active and user.is_staff and user.has_usable_password():
            return user
        return None
