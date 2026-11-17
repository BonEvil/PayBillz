from django.urls import include, path

urlpatterns = [path('', include('hosting.urls')), path('', include('bills.urls'))]
