"""Self-service registration for the Django admin site.

A public form (linked from the admin login page) lets someone request an account. New
sign-ups are created **pending**: ``is_active=False`` blocks login entirely, while
``is_staff=True`` marks them as an intended admin-panel user. An existing admin then
approves them (activate + grant the *Inventory Staff* group) or promotes them to a full
admin (superuser) from the enhanced Users admin — see ``bot/admin.py``.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.urls import reverse


class RegisterForm(UserCreationForm):
    """Username + password (validated by AUTH_PASSWORD_VALIDATORS) with an optional name."""

    first_name = forms.CharField(max_length=150, required=False, label="Name")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name")


def register(request):
    """Render the registration form and create a pending account on valid POST."""
    # Already-signed-in users have no reason to register; send them to the admin.
    if request.user.is_authenticated:
        return redirect("admin:index")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # Pending until an admin approves. is_staff marks intent to use the admin;
            # it stays dormant while is_active is False (inactive users can't authenticate).
            user.is_active = False
            user.is_staff = True
            user.save()
            return render(
                request,
                "admin/register.html",
                {"registered": True, "login_url": reverse("admin:login")},
            )
    else:
        form = RegisterForm()

    return render(
        request,
        "admin/register.html",
        {"form": form, "login_url": reverse("admin:login")},
    )
