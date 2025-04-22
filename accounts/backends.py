from django.contrib.auth.backends import ModelBackend
from accounts.models import Account


class EmailAuthBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email", username)
        try:
            user = Account.objects.get(email=email)
            if user.check_password(password):
                return user
        except Account.DoesNotExist:
            return None
