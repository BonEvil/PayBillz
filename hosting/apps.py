from django.apps import AppConfig

class HostingConfig(AppConfig):
    name = 'hosting'
    def ready(self):
        from . import signals
