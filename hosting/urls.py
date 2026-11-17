from django.urls import path
from django.contrib.auth.views import LogoutView, PasswordChangeView, PasswordChangeDoneView
from .views import OwnerLoginView, backup_callback, backup_status
urlpatterns = [
    path('internal/backup/', backup_callback, name='backup_callback'),
    path('settings/backup/', backup_status, name='backup_status'),
    path('login/', OwnerLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('account/password/', PasswordChangeView.as_view(template_name='hosting/password.html', success_url='/account/password/done/'), name='password_change'),
    path('account/password/done/', PasswordChangeDoneView.as_view(template_name='hosting/password_done.html'), name='password_change_done'),
]
