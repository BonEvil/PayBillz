from django.urls import include, path

urlpatterns = [path('', include('bills.urls'))]
