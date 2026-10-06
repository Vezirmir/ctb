"""E-mail address check: spelling, typos in popular domains and whether the domain receives mail.

The check cannot prove that a mailbox exists (mail servers do not tell that without sending),
but it finds addresses that certainly bounce: broken spelling, domains that do not exist or have
no mail server, and typos like "gmial.com".
"""

import difflib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Email

try:
    import dns.exception
    import dns.resolver
except ImportError:  # pragma: no cover - dnspython is in requirements.txt
    dns = None

DNS_TIMEOUT = 4
DNS_THREADS = 16

# Free mail providers people often misspell.
POPULAR_DOMAINS = [
    "gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com", "yahoo.com",
    "icloud.com", "mail.ru", "inbox.ru", "list.ru", "bk.ru", "yandex.ru", "ya.ru", "yandex.com",
    "rambler.ru", "hotmail.com.tr", "yandex.com.tr", "outlook.com.tr", "mynet.com", "gmx.de",
    "web.de", "t-online.de", "mail.com", "aol.com", "qq.com", "163.com", "126.com", "tut.by",
    "ukr.net", "i.ua", "bigmir.net",
]
BAD_ENDINGS = (".con", ".cmo", ".comm", ".coom", ".om", ".cm", ".co.m", ".ru.ru", ".rru",
               ".nett", ".ogr")


@dataclass
class Result:
    status: str
    note: str = ""


class DnsUnavailable(Exception):
    """The server cannot look up domains, so only spelling can be checked."""


def spelling(address):
    """Result for a broken address, a suggestion for a typo, or None if it looks fine."""
    address = (address or "").strip()
    try:
        validate_email(address)
    except ValidationError:
        return Result(Email.Check.INVALID, _("Not a valid e-mail address"))
    domain = address.rsplit("@", 1)[1].lower()
    if domain in POPULAR_DOMAINS:
        return None
    for ending in BAD_ENDINGS:
        if domain.endswith(ending):
            return Result(Email.Check.SUSPICIOUS,
                          _("Domain ends with “%(ending)s”") % {"ending": ending})
    close = difflib.get_close_matches(domain, POPULAR_DOMAINS, n=1, cutoff=0.85)
    if close:
        return Result(Email.Check.SUSPICIOUS, _("Did you mean %(domain)s?") % {"domain": close[0]})
    return None


def _resolver():
    resolver = dns.resolver.Resolver()
    resolver.lifetime = DNS_TIMEOUT
    resolver.timeout = DNS_TIMEOUT
    return resolver


def domain_result(domain, resolver=None):
    """Result for a domain: receives mail, does not exist, or None if the lookup failed."""
    resolver = resolver or _resolver()
    try:
        answer = resolver.resolve(domain, "MX")
        hosts = [str(r.exchange).rstrip(".") for r in answer]
        if hosts and all(h in ("", ".") for h in hosts):
            return Result(Email.Check.INVALID, _("The domain does not accept e-mail"))
        return Result(Email.Check.VALID)
    except dns.resolver.NXDOMAIN:
        return Result(Email.Check.INVALID, _("The domain does not exist"))
    except dns.resolver.NoAnswer:
        pass
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
        return None
    except dns.exception.DNSException:
        return None
    # No MX record: mail goes to the domain itself if it has an address.
    for record in ("A", "AAAA"):
        try:
            resolver.resolve(domain, record)
            return Result(Email.Check.VALID)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.exception.DNSException:
            return None
    return Result(Email.Check.INVALID, _("The domain has no mail server"))


def check_domains(domains):
    """{domain: Result or None}; raises DnsUnavailable if no lookups work on this server."""
    if dns is None:
        raise DnsUnavailable
    resolver = _resolver()
    if domain_result("gmail.com", resolver) is None:
        raise DnsUnavailable
    domains = sorted(set(domains))
    with ThreadPoolExecutor(max_workers=DNS_THREADS) as pool:
        return dict(zip(domains, pool.map(lambda d: domain_result(d, _resolver()), domains)))


@dataclass
class Report:
    valid: int = 0
    suspicious: int = 0
    invalid: int = 0
    unknown: int = 0
    dns_unavailable: bool = False


def check_emails(queryset):
    """Check the addresses and save the result on each Email record."""
    emails = list(queryset.only("pk", "email"))
    first_pass = {e.pk: spelling(e.email) for e in emails}
    to_lookup = [e.email.rsplit("@", 1)[1].lower() for e in emails
                 if first_pass[e.pk] is None or first_pass[e.pk].status == Email.Check.SUSPICIOUS]
    report = Report()
    try:
        domains = check_domains(to_lookup)
    except DnsUnavailable:
        domains = {}
        report.dns_unavailable = True
    now = timezone.now()
    for email in emails:
        result = first_pass[email.pk]
        if result is None or result.status == Email.Check.SUSPICIOUS:
            domain = domains.get(email.email.rsplit("@", 1)[1].lower())
            if domain is not None and domain.status == Email.Check.INVALID:
                result = domain
            elif result is None:
                result = domain
        if result is None:
            report.unknown += 1
            continue
        setattr(report, result.status, getattr(report, result.status) + 1)
        Email.objects.filter(pk=email.pk).update(
            check_status=result.status, check_note=result.note[:255], checked_at=now)
    return report


def report_message(report):
    parts = [_("OK: %(n)d") % {"n": report.valid},
             _("possible typos: %(n)d") % {"n": report.suspicious},
             _("invalid: %(n)d") % {"n": report.invalid}]
    if report.unknown:
        parts.append(_("not checked: %(n)d") % {"n": report.unknown})
    return ", ".join(parts)

