from django.urls import path
from django.contrib.staticfiles.views import serve as static_serve
from . import views, pwa

app_name = 'bills'
urlpatterns = [
    path('manifest.webmanifest', pwa.asset, {'filename': 'manifest.webmanifest', 'content_type': 'application/manifest+json'}, name='manifest'),
    path('service-worker.js', pwa.asset, {'filename': 'service-worker.js', 'content_type': 'application/javascript'}, name='service_worker'),
    path('pwa/register.js', pwa.asset, {'filename': 'register.js', 'content_type': 'application/javascript'}, name='pwa_register'),
    path('pwa/offline.html', pwa.asset, {'filename': 'offline.html', 'content_type': 'text/html'}, name='offline'),
    path('pwa/icon-192.png', pwa.asset, {'filename': 'icon-192.png', 'content_type': 'image/png'}, name='icon_192'),
    path('pwa/icon-512.png', pwa.asset, {'filename': 'icon-512.png', 'content_type': 'image/png'}, name='icon_512'),
    path('apple-touch-icon.png', pwa.asset, {'filename': 'icon-192.png', 'content_type': 'image/png'}, name='apple_icon'),
    path('favicon.ico', pwa.asset, {'filename': 'icon-192.png', 'content_type': 'image/png'}, name='favicon'),
    path('static/bills/site.css', lambda request: static_serve(request, 'bills/site.css', insecure=True), name='site_css'),
    path('static/bills/app.js', lambda request: static_serve(request, 'bills/app.js', insecure=True), name='app_js'),
    path('', views.dashboard, name='dashboard'),
    path('schedule/', views.schedule_list, name='schedule'),
    path('schedule/new/', views.schedule_edit, name='schedule_new'),
    path('schedule/<int:pk>/edit/', views.schedule_edit, name='schedule_edit'),
    path('schedule/<int:pk>/remove/', views.schedule_delete, name='schedule_delete'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/new/', views.category_edit, name='category_new'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('bills/', views.bill_list, name='bill_list'),
    path('bills/new/', views.bill_edit, name='bill_new'),
    path('bills/<int:pk>/edit/', views.bill_edit, name='bill_edit'),
    path('bills/<int:pk>/archive/', views.bill_archive, name='bill_archive'),
    path('transactions/<str:kind>/<int:pk>/complete/', views.transaction_complete, name='transaction_complete'),
    path('occurrences/<int:pk>/edit/', views.occurrence_edit, name='occurrence_edit'),
    path('occurrences/<int:pk>/pay/', views.payment_edit, name='payment_edit'),
    path('occurrences/<int:pk>/undo/', views.payment_undo, name='payment_undo'),
    path('history/', views.history, name='history'),
]
