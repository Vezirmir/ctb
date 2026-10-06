from django.shortcuts import render


def csrf_failure(request, reason=""):
    """403 page that shows why the form was rejected (the reason is not sensitive)."""
    return render(request, "403_csrf.html", {"reason": reason}, status=403)
