from decimal import Decimal

from django import forms

from accounts.forms import StyledMixin

from .models import LedgerEntry, StudentFeePlan


class PaymentForm(StyledMixin, forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    method = forms.ChoiceField(choices=LedgerEntry.Method.choices)
    entry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), label="Date")
    reference = forms.CharField(max_length=80, required=False, label="Reference / cheque no.")
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class EntryForm(StyledMixin, forms.Form):
    kind = forms.ChoiceField(choices=[("charge", "Other charge (adds to balance)"), ("discount", "Discount / concession (reduces balance)")])
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    description = forms.CharField(max_length=200)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class PlanForm(StyledMixin, forms.ModelForm):
    start_month = forms.DateField(widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"), input_formats=["%Y-%m", "%Y-%m-%d"])

    class Meta:
        model = StudentFeePlan
        fields = ["monthly_amount", "discount", "start_month", "is_active", "note"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()
