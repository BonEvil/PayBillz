from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.template.loader import render_to_string


class AccountSettingsForm(forms.ModelForm):
    email = forms.EmailField(label='Recovery email', required=True,
                             help_text='Password reset links will be sent here.')
    current_password = forms.CharField(label='Current password', strip=False,
                                      widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))

    class Meta:
        model = get_user_model()
        fields = ('username', 'email')
        widgets = {'username': forms.TextInput(attrs={'autocomplete': 'username'})}

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if get_user_model().objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This email is already in use.')
        return email

    def clean_current_password(self):
        password = self.cleaned_data['current_password']
        if not self.instance.check_password(password):
            raise forms.ValidationError('Enter your current password to save account changes.')
        return password


class OwnerPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, oidc_token=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.oidc_token = oidc_token

    def get_users(self, email):
        return (user for user in super().get_users(email) if user.is_superuser)

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        from .email import send_recovery_email
        subject = ''.join(render_to_string(subject_template_name, context).splitlines())
        body = render_to_string(email_template_name, context)
        send_recovery_email(to_email, subject, body, self.oidc_token)
