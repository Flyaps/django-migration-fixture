import os
import glob

from io import StringIO

from django.apps import apps
from django.core import management
from django.db.migrations import writer
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Locate files and create data migrations for them."

    def handle(self, *args, **options):
        fixture_file = options['file'] if options['file'] else 'initial_data'
        fixture_template = f"{fixture_file}.*"
        applied_number = 0

        for app in apps.get_app_configs():
            for fixture_path in glob.glob(os.path.join(app.path, 'fixtures', fixture_template)):
                if not glob.glob(os.path.join(app.path, 'migrations', '0001*')):
                    self.stdout.write(self.style.MIGRATE_HEADING(f"Migrations for '{app.label}':\n"))
                    self.stdout.write(
                        self.style.WARNING(f"Ignoring '{os.path.basename(fixture_path)}' - not migrated.\n")
                    )
                    self.stdout.write(
                        self.style.WARNING('There are no migrations at all\n')
                    )
                    continue

                if self.migration_exists(app, fixture_path):
                    self.stdout.write(self.style.MIGRATE_HEADING(f"Migrations for '{app.label}':\n"))
                    self.stdout.write(
                        self.style.NOTICE(
                            f"Ignoring '{os.path.basename(fixture_path)}' - migration already exists.\n"
                        )
                    )
                    continue

                self.create_migration(app, fixture_path)
                applied_number += 1

        self.stdout.write(
            self.style.SUCCESS(f'{applied_number} fixtures has been loaded')
        )

    def monkey_patch_migration_template(self, app, fixture_path):
        """
        Monkey patch the django.db.migrations.writer.MIGRATION_TEMPLATE

        Monkey patching django.db.migrations.writer.MIGRATION_TEMPLATE means that we
        don't have to do any complex regex or reflection.

        It's hacky... but works atm.
        """
        self._MIGRATION_TEMPLATE = writer.MIGRATION_TEMPLATE
        module_split = app.module.__name__.split('.')

        if len(module_split) == 1:
            module_import = "import %s\n" % module_split[0]
        else:
            module_import = "from %s import %s\n" % (
                '.'.join(module_split[:-1]),
                module_split[-1:][0],
            )

        writer.MIGRATION_TEMPLATE = writer.MIGRATION_TEMPLATE.replace(
            '%(imports)s',
            "%(imports)s" + "\nfrom django_migration_fixture import fixture\n%s" % module_import
        ).replace(
            '%(operations)s',
            "        migrations.RunPython(**fixture(%s, ['%s'])),\n" % (
                app.label,
                os.path.basename(fixture_path)
            ) + "%(operations)s\n"
        )

    def restore_migration_template(self):
        """
        Restore the migration template.
        """
        writer.MIGRATION_TEMPLATE = self._MIGRATION_TEMPLATE

    def migration_exists(self, app, fixture_path):
        """
        Return true if it looks like a migration already exists.
        """
        base_name = os.path.basename(fixture_path)
        # Loop through all migrations
        for migration_path in glob.glob(os.path.join(app.path, 'migrations', '*.py')):
            if base_name in open(migration_path).read():
                return True
        return False

    def create_migration(self, app, fixture_path):
        """
        Create a data migration for app that uses fixture_path.
        """
        self.monkey_patch_migration_template(app, fixture_path)

        out = StringIO()
        management.call_command('makemigrations', app.label, empty=True, stdout=out)

        self.restore_migration_template()
        self.stdout.write(out.getvalue())

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str)
