from django.conf import settings
from django.db import models
from django.db.models import Q


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=120, blank=True)
    isbn = models.CharField(max_length=20, blank=True)
    shelf = models.CharField(max_length=30, blank=True)
    copies = models.PositiveSmallIntegerField(default=1)
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.SET_NULL, related_name="books")

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    @property
    def on_loan(self):
        return self.loans.filter(returned_on__isnull=True).count()

    @property
    def available(self):
        return max(self.copies - self.on_loan, 0)


class Loan(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="loans")
    borrower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="loans")
    issued_on = models.DateField()
    due_on = models.DateField()
    returned_on = models.DateField(null=True, blank=True)
    fine = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["returned_on", "due_on"]
        constraints = [models.CheckConstraint(condition=Q(fine__gte=0), name="loan_fine_nonneg")]


class Route(models.Model):
    name = models.CharField(max_length=80)
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.SET_NULL, related_name="routes")
    vehicle_no = models.CharField(max_length=30, blank=True)
    driver_name = models.CharField(max_length=80, blank=True)
    driver_phone = models.CharField(max_length=30, blank=True)
    capacity = models.PositiveSmallIntegerField(default=30)
    monthly_fee = models.DecimalField(max_digits=9, decimal_places=2, default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def seats_left(self):
        return max(self.capacity - self.riders.count(), 0)


class RouteStudent(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="riders")
    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="route_assignment")
    stop = models.CharField(max_length=80, blank=True)
