from django.urls import path
from django.contrib.staticfiles.views import serve as static_serve
from . import views

app_name = 'bills'
urlpatterns = [
    path('static/bills/site.css', lambda request: static_serve(request, 'bills/site.css', insecure=True), name='site_css'),
    path('', views.dashboard, name='dashboard'),
    path('schedule/', views.schedule_edit, name='schedule'),
    path('bills/', views.bill_list, name='bill_list'),
    path('bills/new/', views.bill_edit, name='bill_new'),
    path('bills/<int:pk>/edit/', views.bill_edit, name='bill_edit'),
    path('bills/<int:pk>/archive/', views.bill_archive, name='bill_archive'),
    path('occurrences/<int:pk>/edit/', views.occurrence_edit, name='occurrence_edit'),
    path('occurrences/<int:pk>/pay/', views.payment_edit, name='payment_edit'),
    path('occurrences/<int:pk>/undo/', views.payment_undo, name='payment_undo'),
    path('history/', views.history, name='history'),
]
