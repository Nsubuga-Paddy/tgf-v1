from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from phonenumber_field.modelfields import PhoneNumberField  # Optional, see notes
from django.db import transaction  # Add this import
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from datetime import date
import json


class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    projects = models.ManyToManyField(Project, blank=True, related_name='users')
    full_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone_number = PhoneNumberField(region='UG', blank=True, null=True)
    national_id = models.CharField(max_length=20, unique=True, blank=True, null=True)
    account_number = models.CharField(
        max_length=20, unique=True, blank=True, null=True,
        help_text="Auto-generated: MCSTGF-<Initials><0001…>"
    )
    address = models.TextField(blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    is_admin = models.BooleanField(default=False)  # ← Merge this here
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.account_number:
            initials = (f"{self.user.last_name[:1]}{self.user.first_name[:1]}").upper()
            prefix = "MCSTGF"
            earlier = UserProfile.objects.filter(
                user__date_joined__lt=self.user.date_joined
            ).count()
            seq_str = str(earlier + 1).zfill(4)
            self.account_number = f"{prefix}-{initials}{seq_str}"
            with transaction.atomic():
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        return self.user.username


#52Weeks Savings Model Structure
class SavingsTransaction(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='savings_transactions')
    amount = models.PositiveIntegerField(default=0)
    receipt_number = models.CharField(max_length=20, blank=True, null=True, help_text="Receipt number for this deposit")
    date_saved = models.DateTimeField(default=timezone.now)
    
    cumulative_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fully_covered_weeks = models.JSONField(default=list) 
    next_week = models.PositiveIntegerField(default=1)
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = "tgfs_savingstransaction"
        ordering = ['-date_saved']
        verbose_name = "52 WSC Savings Transaction"
        verbose_name_plural = "52 WSC Savings Transactions"

    def __str__(self):
        return f"{self.user_profile.user.username} - {self.amount} on {self.date_saved.date()}"

class Investment(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='investments')
    amount_invested = models.DecimalField(max_digits=12, decimal_places=2)
    interest_rate = models.FloatField(help_text="Annual interest rate (e.g., 12.5 for 12.5%)")
    maturity_months = models.PositiveIntegerField(default=8)
    date_invested = models.DateField(default=timezone.now)

    @property
    def maturity_date(self):
        return self.date_invested + timedelta(days=30 * self.maturity_months)

    @property
    def interest_expected(self):
        # Using simple interest
        return self.amount_invested * Decimal(self.interest_rate / 100) * Decimal(self.maturity_months / 12)

    @property
    def interest_gained_so_far(self):
        # Calculate interest on a daily basis for more accuracy
        days_elapsed = (timezone.now().date() - self.date_invested).days
        days_elapsed = max(0, min(days_elapsed, self.maturity_months * 30))  # Cap at maturity
        
        # Daily interest rate = annual rate / 365
        daily_rate = self.interest_rate / 100 / 365
        
        # Calculate interest earned so far
        interest_earned = self.amount_invested * Decimal(daily_rate) * days_elapsed
        
        return interest_earned

    def __str__(self):
        return f"{self.user_profile.user.username} - UGX {self.amount_invested:,.0f} at {self.interest_rate}%"

    class Meta:
        verbose_name = "52 WSC Investment"
        verbose_name_plural = "52 WSC Investments"

#Club Model Structure
class Club(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    monthly_target = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Monthly savings target for the club")
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_monthly_collection(self, year=None, month=None):
        from django.utils import timezone
        if year is None or month is None:
            now = timezone.now()
            year = now.year
            month = now.month
        return self.transactions.filter(
            transaction_type='deposit',
            created_at__year=year,
            created_at__month=month
        ).aggregate(total=models.Sum('amount'))['total'] or 0

    def get_monthly_progress(self, year=None, month=None):
        if self.monthly_target <= 0:
            return 0
        collection = self.get_monthly_collection(year, month)
        return min((collection / self.monthly_target) * 100, 100)

    @property
    def available_savings(self):
        deposits = self.transactions.filter(transaction_type='deposit').aggregate(total=models.Sum('amount'))['total'] or 0
        withdrawals = self.transactions.filter(transaction_type='withdrawal').aggregate(total=models.Sum('amount'))['total'] or 0
        fixed = self.fixed_savings.filter(is_active=True).aggregate(total=models.Sum('amount_fixed'))['total'] or 0
        return deposits - withdrawals - fixed


class ClubMembership(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE,null=True, blank=True)
    club = models.ForeignKey(Club, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    role = models.CharField(max_length=50, choices=[('member', 'Member'), ('admin', 'Club Admin')], default='member')
    joined_on = models.DateField(default=timezone.now)


    class Meta:
        unique_together = ('user_profile', 'club')

    def __str__(self):
        if self.user_profile and self.user_profile.user:
            return f"{self.user_profile.user.username} in {self.club.name}"
        else:
            return f"Unknown member in {self.club.name}"


class ClubTransaction(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='transactions')  # <-- important
    user_profile = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=[('deposit', 'Deposit'), ('withdrawal', 'Withdrawal')])
    receipt_number = models.CharField(max_length=20, blank=True, null=True, help_text="Receipt number for this transaction")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        user = self.user_profile.user.username if self.user_profile else 'N/A'
        return f"{self.transaction_type.title()} of {self.amount} by {user}"


from django.core.exceptions import ValidationError

class ClubFixedSavings(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='fixed_savings')
    amount_fixed = models.DecimalField(max_digits=12, decimal_places=2)
    receipt_number = models.CharField(max_length=20, blank=True, null=True, help_text="Receipt number for this fixed savings")
    interest_rate = models.FloatField(help_text="Annual interest rate (e.g., 10.0 for 10%)")
    maturity_months = models.PositiveIntegerField(default=8)
    date_fixed = models.DateField(default=date.today, help_text="When the investment was made")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_fixed_savings')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def clean(self):
        if self.club and self.amount_fixed and self.amount_fixed > 0:
            available = self.club.available_savings
            
            # If this is an existing record being updated, add back its current amount
            if self.pk:
                try:
                    current_amount = ClubFixedSavings.objects.get(pk=self.pk).amount_fixed
                    available += current_amount
                except ClubFixedSavings.DoesNotExist:
                    pass
            
            if self.amount_fixed > available:
                raise ValidationError(f"Cannot fix UGX {self.amount_fixed:,.0f}. Only UGX {available:,.0f} is available.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def maturity_date(self):
        return self.date_fixed + timedelta(days=30 * self.maturity_months)

    @property
    def expected_interest(self):
        if not self.amount_fixed or not self.interest_rate or not self.maturity_months:
            return Decimal(0)
        return self.amount_fixed * Decimal(self.interest_rate / 100) * Decimal(self.maturity_months / 12)

    @property
    def interest_gained_so_far(self):
        if not self.amount_fixed or not self.interest_rate or not self.date_fixed or not self.maturity_months:
            return Decimal(0)
        days_elapsed = (timezone.now().date() - self.date_fixed).days
        days_elapsed = max(0, min(days_elapsed, self.maturity_months * 30))
        daily_rate = self.interest_rate / 100 / 365
        return self.amount_fixed * Decimal(daily_rate) * days_elapsed

    @property
    def status(self):
        return 'matured' if timezone.now().date() >= self.maturity_date else 'active'
    
    @property
    def available_to_fix(self):
        deposits = self.club.transactions.filter(transaction_type='deposit').aggregate(total=models.Sum('amount'))['total'] or 0
        withdrawals = self.club.transactions.filter(transaction_type='withdrawal').aggregate(total=models.Sum('amount'))['total'] or 0
        fixed = self.club.fixed_savings.filter(is_active=True).aggregate(total=models.Sum('amount_fixed'))['total'] or 0
        return deposits - withdrawals - fixed

    def __str__(self):
        amount = self.amount_fixed or 0
        rate = self.interest_rate or 0
        return f"{self.club.name} - UGX {amount:,.0f} at {rate}%"


class ClubEvent(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='events')
    title = models.CharField(max_length=200, help_text="Title of the event")
    event_date = models.DateField(help_text="Date when the event will take place")
    description = models.TextField(help_text="Event details and description")
    location = models.CharField(max_length=200, help_text="Location where the event will be held")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_club_events')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['event_date']
        verbose_name = "Club Event"
        verbose_name_plural = "Club Events"

    @property
    def status(self):
        """Returns the status of the event based on the date"""
        if not self.event_date:
            return 'pending'
        today = timezone.now().date()
        if self.event_date < today:
            return 'past'
        elif self.event_date == today:
            return 'today'
        else:
            return 'upcoming'

    def __str__(self):
        return f"{self.club.name} - {self.title} ({self.event_date})"

#Individual User Fixed Savings Model Structure
class IndividualUserFixedSavings(models.Model):
    """Fixed Savings Account for individual users"""
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='fixed_savings')
    account_number = models.CharField(max_length=20, help_text="User's unique account number")
    
    # Investment Details
    principal_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Initial amount invested")
    interest_rate = models.FloatField(default=12.75, help_text="Annual interest rate (e.g., 12.75 for 12.75%)")
    maturity_period = models.PositiveIntegerField(default=8, help_text="Duration in months (6, 12, 24, etc.)")
    date_fixed = models.DateField(default=date.today, help_text="When the investment was made")
    maturity_date = models.DateField(help_text="When the investment matures")
    compounding_frequency = models.CharField(
        max_length=20, 
        choices=[('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('annually', 'Annually')],
        default='monthly'
    )
    
    # Financial Tracking
    expected_interest = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    interest_earned_so_far = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    matured_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Maturity Management
    maturity_option = models.CharField(
        max_length=20,
        choices=[('withdraw', 'Withdraw'), ('reinvest', 'Reinvest'), ('partial', 'Partial Withdrawal')],
        default='withdraw'
    )
    reinvestment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    withdrawal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Transaction History
    last_interest_credit_date = models.DateField(null=True, blank=True)
    total_interest_credited = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_interest = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Status and Metadata
    account_status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('matured', 'Matured'), ('closed', 'Closed')],
        default='active'
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=[('deposit', 'Deposit'), ('withdrawal', 'Withdrawal'), ('reinvestment', 'Reinvestment')],
        default='deposit',
        help_text="Type of transaction for this fixed savings"
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Individual User Fixed Savings"
        verbose_name_plural = "Individual User Fixed Savings"
        ordering = ['-date_fixed']

    def save(self, *args, **kwargs):
        # Set account number from user profile if not provided
        if not self.account_number and self.user_profile:
            self.account_number = self.user_profile.account_number
        
        # Calculate maturity date if not provided
        if not self.maturity_date and self.date_fixed and self.maturity_period:
            self.maturity_date = self.date_fixed + timedelta(days=30 * self.maturity_period)
        
        # Calculate expected interest
        if self.principal_amount and self.interest_rate and self.maturity_period:
            # Simple interest calculation
            self.expected_interest = self.principal_amount * Decimal(self.interest_rate / 100) * Decimal(self.maturity_period / 12)
            self.matured_amount = self.principal_amount + self.expected_interest
        
        super().save(*args, **kwargs)

    @property
    def days_elapsed(self):
        """Days since investment started"""
        if self.date_fixed:
            return (timezone.now().date() - self.date_fixed).days
        return 0

    @property
    def days_remaining(self):
        """Days until maturity"""
        if self.maturity_date:
            remaining = (self.maturity_date - timezone.now().date()).days
            return max(0, remaining)
        return 0

    @property
    def interest_rate_per_day(self):
        """Daily interest rate"""
        if self.interest_rate is not None:
            return self.interest_rate / 100 / 365
        return 0

    @property
    def maturity_status(self):
        """Whether the investment has matured"""
        if self.maturity_date:
            return timezone.now().date() >= self.maturity_date
        return False

    @property
    def progress_percentage(self):
        """Investment progress as percentage"""
        if self.maturity_period and self.maturity_period > 0:
            elapsed_months = self.days_elapsed / 30
            return min((elapsed_months / self.maturity_period) * 100, 100)
        return 0

    def calculate_interest_earned_so_far(self):
        """Calculate interest earned up to current date"""
        if self.principal_amount and self.interest_rate and self.principal_amount > 0 and self.interest_rate > 0:
            days_elapsed = min(self.days_elapsed, self.maturity_period * 30) if self.maturity_period else 0
            daily_rate = self.interest_rate / 100 / 365
            return self.principal_amount * Decimal(daily_rate) * days_elapsed
        return Decimal('0.00')

    def __str__(self):
        return f"{self.user_profile.user.username} - {self.principal_amount} at {self.interest_rate}% ({self.maturity_period} months)"


@receiver(post_save, sender=User)
def manage_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(
            user=instance,
            full_name=f"{instance.first_name} {instance.last_name}",
            email=instance.email
        )
    else:
        instance.profile.save()


# Commercial Goat Farming Models
class GoatFarmingPackage(models.Model):
    """Investment packages for goat farming"""
    name = models.CharField(max_length=100, help_text="Package name (e.g., Basic Package)")
    description = models.TextField(help_text="Package description and benefits")
    
    # Package Investment Details
    total_package_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Total investment amount for the entire package")
    
    # Initial Goats Provided
    number_of_female_goats = models.PositiveIntegerField(help_text="Number of female goats included in the package")
    number_of_male_goats = models.PositiveIntegerField(default=0, help_text="Number of male goats included in the package")
    
    # Expected Returns
    expected_offspring_in_one_year = models.PositiveIntegerField(default=0, help_text="Expected number of offspring after 1 year of breeding")
    
    # Management Fee Structure
    management_fee = models.DecimalField(max_digits=12, decimal_places=2, help_text="Annual management fee for this package")
    management_fee_goat_count = models.PositiveIntegerField(default=1, help_text="Number of goats this management fee covers")
    
    # Breeding Period
    breeding_period_months = models.PositiveIntegerField(default=12, help_text="Expected breeding period in months (default 1 year)")
    
    # Package Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Goat Farming Package"
        verbose_name_plural = "Goat Farming Packages"
        ordering = ['total_package_amount']

    @property
    def total_initial_goats(self):
        """Total number of goats provided initially"""
        female_goats = self.number_of_female_goats or 0
        male_goats = self.number_of_male_goats or 0
        return female_goats + male_goats

    @property
    def expected_total_after_one_year(self):
        """Expected total goats after 1 year (initial + offspring)"""
        initial_goats = self.total_initial_goats
        offspring = self.expected_offspring_in_one_year or 0
        return initial_goats + offspring

    @property
    def management_fee_per_goat(self):
        """Management fee per goat"""
        if (self.management_fee_goat_count and self.management_fee_goat_count > 0 and 
            self.management_fee is not None):
            return self.management_fee / self.management_fee_goat_count
        return 0

    def __str__(self):
        return f"{self.name} - UGX {self.total_package_amount:,.0f} ({self.total_initial_goats} goats)"


class GoatFarmingInvestment(models.Model):
    """Individual goat farming investments"""
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='goat_investments')
    package = models.ForeignKey(GoatFarmingPackage, on_delete=models.CASCADE, related_name='investments')
    
    # Investment Details
    investment_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount invested (should match package total_package_amount)")
    receipt_number = models.CharField(max_length=50, blank=True, null=True, help_text="Receipt number for the initial investment")
    start_date = models.DateField(default=date.today, help_text="Investment start date")
    expected_completion_date = models.DateField(help_text="Expected completion date")
    
    # Goat Tracking
    initial_goats_received = models.PositiveIntegerField(default=0, help_text="Initial goats received from package")
    offspring_received = models.PositiveIntegerField(default=0, help_text="Offspring received so far")
    total_goats_current = models.PositiveIntegerField(default=0, help_text="Total goats currently owned")
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
            ('suspended', 'Suspended')
        ],
        default='active'
    )
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Goat Farming Investment"
        verbose_name_plural = "Goat Farming Investments"
        ordering = ['-start_date']

    def save(self, *args, **kwargs):
        # Always calculate expected completion date based on package breeding period
        if self.start_date and self.package and self.package.breeding_period_months:
            self.expected_completion_date = self.start_date + timedelta(days=30 * self.package.breeding_period_months)
        
        # Update total goats current
        self.total_goats_current = self.initial_goats_received + self.offspring_received
        
        super().save(*args, **kwargs)

    @property
    def breeding_period_months(self):
        """Breeding period from package"""
        if self.package:
            return self.package.breeding_period_months
        return 0

    @property
    def expected_initial_goats(self):
        """Expected initial goats from package"""
        if self.package:
            return self.package.total_initial_goats
        return 0

    @property
    def expected_offspring(self):
        """Expected offspring from package"""
        if self.package:
            return self.package.expected_offspring_in_one_year
        return 0

    @property
    def expected_total_goats(self):
        """Expected total goats after 1 year"""
        if self.package:
            return self.package.expected_total_after_one_year
        return 0

    @property
    def goats_received_percentage(self):
        """Percentage of initial goats received"""
        if self.expected_initial_goats > 0:
            return (self.initial_goats_received / self.expected_initial_goats) * 100
        return 0

    @property
    def offspring_percentage(self):
        """Percentage of expected offspring received"""
        if self.expected_offspring > 0:
            return (self.offspring_received / self.expected_offspring) * 100
        return 0

    @property
    def total_progress_percentage(self):
        """Overall progress percentage"""
        if self.expected_total_goats > 0:
            return (self.total_goats_current / self.expected_total_goats) * 100
        return 0

    @property
    def days_elapsed(self):
        """Days since investment started"""
        if self.start_date:
            return (timezone.now().date() - self.start_date).days
        return 0

    @property
    def days_remaining(self):
        """Days until expected completion"""
        if self.expected_completion_date:
            remaining = (self.expected_completion_date - timezone.now().date()).days
            return max(0, remaining)
        return 0

    @property
    def progress_percentage(self):
        """Investment progress as percentage"""
        if self.package and self.package.breeding_period_months:
            elapsed_months = self.days_elapsed / 30
            return min((elapsed_months / self.package.breeding_period_months) * 100, 100)
        return 0

    def __str__(self):
        return f"{self.user_profile.user.username} - {self.package.name}"


class Goat(models.Model):
    """Individual goat records"""
    GENDER_CHOICES = [
        ('female', 'Female'),
        ('male', 'Male'),
    ]
    
    HEALTH_STATUS_CHOICES = [
        ('healthy', 'Healthy'),
        ('under_observation', 'Under Observation'),
        ('sick', 'Sick'),
        ('recovered', 'Recovered'),
    ]

    investment = models.ForeignKey(GoatFarmingInvestment, on_delete=models.CASCADE, related_name='goats')
    goat_id = models.CharField(max_length=20, unique=True, help_text="Unique goat identifier")
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    breed = models.CharField(max_length=50, help_text="Goat breed")
    date_received = models.DateField(default=date.today, help_text="Date goat was received")
    health_status = models.CharField(max_length=20, choices=HEALTH_STATUS_CHOICES, default='healthy')
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Current weight in kg")
    age_months = models.PositiveIntegerField(null=True, blank=True, help_text="Age in months")
    is_pregnant = models.BooleanField(default=False, help_text="Whether the goat is pregnant")
    expected_delivery_date = models.DateField(null=True, blank=True, help_text="Expected delivery date if pregnant")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Goat"
        verbose_name_plural = "Goats"
        ordering = ['goat_id']

    def save(self, *args, **kwargs):
        # Auto-generate goat ID if not provided
        if not self.goat_id:
            last_goat = Goat.objects.order_by('-id').first()
            if last_goat:
                last_number = int(last_goat.goat_id[2:]) if last_goat.goat_id.startswith('GF') else 0
                self.goat_id = f"GF{(last_number + 1):03d}"
            else:
                self.goat_id = "GF001"
        super().save(*args, **kwargs)

    @property
    def is_female(self):
        return self.gender == 'female'

    @property
    def is_male(self):
        return self.gender == 'male'

    def __str__(self):
        return f"{self.goat_id} - {self.breed} ({self.gender})"


class GoatHealthRecord(models.Model):
    """Health records for individual goats"""
    goat = models.ForeignKey(Goat, on_delete=models.CASCADE, related_name='health_records')
    date = models.DateField(default=date.today)
    health_status = models.CharField(max_length=20, choices=Goat.HEALTH_STATUS_CHOICES)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    symptoms = models.TextField(blank=True, null=True, help_text="Any symptoms observed")
    treatment = models.TextField(blank=True, null=True, help_text="Treatment provided")
    veterinarian = models.CharField(max_length=100, blank=True, null=True, help_text="Veterinarian name")
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Treatment cost")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Goat Health Record"
        verbose_name_plural = "Goat Health Records"
        ordering = ['-date']

    def __str__(self):
        return f"{self.goat.goat_id} - {self.health_status} on {self.date}"


class GoatOffspring(models.Model):
    """Offspring tracking for goats"""
    mother = models.ForeignKey(Goat, on_delete=models.CASCADE, related_name='offspring', limit_choices_to={'gender': 'female'})
    father = models.ForeignKey(Goat, on_delete=models.CASCADE, related_name='sired_offspring', limit_choices_to={'gender': 'male'}, null=True, blank=True)
    offspring_id = models.CharField(max_length=20, unique=True, help_text="Unique offspring identifier")
    gender = models.CharField(max_length=10, choices=Goat.GENDER_CHOICES)
    birth_date = models.DateField(help_text="Date of birth")
    weight_at_birth = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, help_text="Weight at birth in kg")
    is_alive = models.BooleanField(default=True, help_text="Whether the offspring is alive")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Goat Offspring"
        verbose_name_plural = "Goat Offspring"
        ordering = ['-birth_date']

    def save(self, *args, **kwargs):
        # Auto-generate offspring ID if not provided
        if not self.offspring_id:
            last_offspring = GoatOffspring.objects.order_by('-id').first()
            if last_offspring:
                last_number = int(last_offspring.offspring_id[3:]) if last_offspring.offspring_id.startswith('OFF') else 0
                self.offspring_id = f"OFF{(last_number + 1):03d}"
            else:
                self.offspring_id = "OFF001"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.offspring_id} - {self.mother.goat_id}'s offspring"


class GoatFarmingTransaction(models.Model):
    """Financial transactions for goat farming"""
    TRANSACTION_TYPES = [
        ('investment', 'Investment'),
        ('payment', 'Payment'),
        ('management_fee', 'Management Fee'),
        ('veterinary_cost', 'Veterinary Cost'),
        ('feed_cost', 'Feed Cost'),
        ('other_expense', 'Other Expense'),
        ('returns', 'Returns'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ]

    investment = models.ForeignKey(GoatFarmingInvestment, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(help_text="Transaction description")
    reference_number = models.CharField(max_length=50, blank=True, null=True, help_text="Payment reference number")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    due_date = models.DateField(null=True, blank=True, help_text="Due date for pending payments")
    processed_date = models.DateTimeField(null=True, blank=True, help_text="Date when transaction was processed")
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_goat_transactions')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Goat Farming Transaction"
        verbose_name_plural = "Goat Farming Transactions"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.investment.user_profile.user.username} - {self.transaction_type} - UGX {self.amount:,.0f}"


class ManagementFeeTier(models.Model):
    """Management fee tiers based on number of goats"""
    tier_name = models.CharField(max_length=50, help_text="Tier name (e.g., Tier 1, Tier 2)")
    min_goats = models.PositiveIntegerField(help_text="Minimum number of goats for this tier")
    max_goats = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum number of goats for this tier (null for unlimited)")
    annual_fee = models.DecimalField(max_digits=12, decimal_places=2, help_text="Annual management fee")
    description = models.TextField(blank=True, null=True, help_text="Tier description and benefits")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Management Fee Tier"
        verbose_name_plural = "Management Fee Tiers"
        ordering = ['min_goats']

    def __str__(self):
        return f"{self.tier_name} - UGX {self.annual_fee:,.0f}"


class GoatFarmingNotification(models.Model):
    """Notifications for goat farming events"""
    NOTIFICATION_TYPES = [
        ('health_alert', 'Health Alert'),
        ('breeding_reminder', 'Breeding Reminder'),
        ('delivery_expected', 'Delivery Expected'),
        ('payment_due', 'Payment Due'),
        ('investment_update', 'Investment Update'),
        ('general', 'General'),
    ]

    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='goat_notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200, help_text="Notification title")
    message = models.TextField(help_text="Notification message")
    is_read = models.BooleanField(default=False, help_text="Whether the notification has been read")
    related_goat = models.ForeignKey(Goat, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    related_investment = models.ForeignKey(GoatFarmingInvestment, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Goat Farming Notification"
        verbose_name_plural = "Goat Farming Notifications"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_profile.user.username} - {self.notification_type} - {self.title}"









