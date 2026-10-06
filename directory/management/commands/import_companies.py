from django.core.management.base import BaseCommand, CommandError

from directory.importer import import_path


class Command(BaseCommand):
    help = (
        "Import company lists from Excel. PATH may be a folder laid out as "
        "<Industry>/<Country>/<file>.xlsx, a .zip archive of such a folder, or a single .xlsx file."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, path, **options):
        try:
            report = import_path(path)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        for warning in report.warnings:
            self.stderr.write(self.style.WARNING(warning))
        self.stdout.write(self.style.SUCCESS(report.summary()))
