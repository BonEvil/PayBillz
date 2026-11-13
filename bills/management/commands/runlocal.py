import os

from django.core.management import BaseCommand, CommandError, call_command

class Command(BaseCommand):
    help = 'Migrate and serve PayBillz on loopback only (default 127.0.0.1:8765).'

    def add_arguments(self, parser):
        parser.add_argument('--port', type=int, default=None)
        parser.add_argument('--host', default='127.0.0.1')
        parser.add_argument('--noreload', action='store_true', help='Accepted for compatibility; reload is disabled by default')

    def handle(self, *args, **options):
        if options['host'] != '127.0.0.1':
            raise CommandError('runlocal binds only to 127.0.0.1')
        raw_port = options['port'] if options['port'] is not None else os.environ.get('PAYBILLZ_PORT', '8765')
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise CommandError('Port must be an integer from 1 to 65535') from exc
        if not 1 <= port <= 65535:
            raise CommandError('Port must be 1–65535')
        call_command('migrate', interactive=False, verbosity=options['verbosity'])
        call_command('runserver', f"127.0.0.1:{port}", use_reloader=False, verbosity=options['verbosity'])
