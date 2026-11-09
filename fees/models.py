from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

MONEY = dict(max_digits=12, decimal_places=2)


class FeeDefault(models.Model):
    """Monthly fee charged to every student of a class unless the student has their own plan."""

    school_class = models.OneToOneField("academics.SchoolClass", on_delete=models.CASCADE, related_name="fee_default")
    monthly_amount = models.DecimalField(validators=[MinValueValidator(0)], **MONEY)

    def __str__(self):
        return f"{self.school_class}: {self.monthly_amount}"


class StudentFeePlan(models.Model):
    """One student's monthly fee: optional own amount (else the class default) minus a fixed monthly discount."""

    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fee_plan")
    monthly_amount = models.DecimalField(null=True, blank=True, validators=[MinValueValidator(0)],
                                         help_text="Leave empty to use the class fee.", **MONEY)
    discount = models.DecimalField(default=Decimal("0"), validators=[MinValueValidator(0)],
                                   help_text="Fixed concession taken off every month (scholarship, sibling discount).", **MONEY)
    start_month = models.DateField(help_text="First month to bill (always day 1).")
    is_active = models.BooleanField(default=True, help_text="Untick to stop monthly billing (e.g. withdrawn student).")
    note = models.CharField(max_length=200, blank=True)

    def save(self, *args, **kwargs):
        self.start_month = self.start_month.replace(day=1)
        super().save(*args, **kwargs)


class LedgerEntry(models.Model):
    """Append-only account book. Mistakes are voided (kept, excluded from the balance), never deleted."""

    class Kind(models.TextChoices):
        MONTHLY = "monthly", "Monthly fee"
        CHARGE = "charge", "Other charge"
        PAYMENT = "payment", "Payment"
        DISCOUNT = "discount", "Discount / concession"

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK = "bank", "Bank transfer"
        ONLINE = "online", "Online"
        CHEQUE = "cheque", "Cheque"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ledger")
    entry_date = models.DateField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    month = models.DateField(null=True, blank=True, help_text="Billing month (day 1) for monthly fees")
    description = models.CharField(max_length=200, blank=True)
    debit = models.DecimalField(default=Decimal("0"), **MONEY)    # what the student owes
    credit = models.DecimalField(default=Decimal("0"), **MONEY)   # what the student paid / was forgiven
    method = models.CharField(max_length=10, choices=Method.choices, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    receipt_no = models.CharField(max_length=20, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=200, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["entry_date", "id"]
        indexes = [models.Index(fields=["student", "is_void"])]
        constraints = [
            models.UniqueConstraint(fields=["student", "month"], condition=Q(kind="monthly", is_void=False), name="one_monthly_fee_per_month"),
            models.CheckConstraint(condition=Q(debit__gte=0) & Q(credit__gte=0), name="ledger_non_negative"),
        ]

    def __str__(self):
        return f"{self.student} {self.kind} {self.debit or self.credit}"
