from django.core.management.base import BaseCommand

from directory.email_check import check_emails, report_message
from directory.models import Email


class Command(BaseCommand):
    help = "Check e-mail addresses: spelling, typos and whether the domain receives mail."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true",
                            help="Check every address again, not only unchecked ones.")

    def handle(self, *args, **options):
        queryset = Email.objects.all() if options["all"] else Email.objects.filter(check_status="")
        self.stdout.write(f"Checking {queryset.count()} addresses…")
        report = check_emails(queryset)
        if report.dns_unavailable:
            self.stderr.write("Domain lookups do not work on this server; only spelling was checked.")
        self.stdout.write(self.style.SUCCESS(report_message(report)))
