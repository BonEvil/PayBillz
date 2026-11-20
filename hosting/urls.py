from django.urls import path
from django.contrib.auth.views import LogoutView, PasswordChangeView, PasswordChangeDoneView, PasswordResetDoneView, PasswordResetConfirmView, PasswordResetCompleteView
from .views import OwnerLoginView, backup_callback, backup_status, account_settings, OwnerPasswordResetView, OwnerPasswordResetConfirmView
urlpatterns = [
    path('settings/', account_settings, name='account_settings'),
    path('password-reset/', OwnerPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/sent/', PasswordResetDoneView.as_view(template_name='hosting/password_reset_done.html'), name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/', OwnerPasswordResetConfirmView.as_view(template_name='hosting/password_reset_confirm.html', success_url='/password-reset/complete/'), name='password_reset_confirm'),
    path('password-reset/complete/', PasswordResetCompleteView.as_view(template_name='hosting/password_reset_complete.html'), name='password_reset_complete'),
    path('internal/backup/', backup_callback, name='backup_callback'),
    path('settings/backup/', backup_status, name='backup_status'),
    path('login/', OwnerLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('account/password/', PasswordChangeView.as_view(template_name='hosting/password.html', success_url='/account/password/done/'), name='password_change'),
    path('account/password/done/', PasswordChangeDoneView.as_view(template_name='hosting/password_done.html'), name='password_change_done'),
]
