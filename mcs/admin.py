from django.contrib import admin
from .models import Project, UserProfile, SavingsTransaction, Investment
from .models import Club, UserProfile, ClubMembership, ClubTransaction, ClubFixedSavings, ClubEvent, IndividualUserFixedSavings, GoatFarmingPackage
from .models import GoatFarmingInvestment, Goat, GoatHealthRecord, GoatOffspring, GoatFarmingTransaction, ManagementFeeTier, GoatFarmingNotification
from django.db import models


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'full_name', 'email', 'account_number', 'is_admin']
    list_filter = ['projects', 'is_admin']
    search_fields = ['user__username', 'full_name', 'account_number', 'user__email']
    filter_horizontal = ('projects',)



class SavingsTransactionInline(admin.TabularInline):
    model = SavingsTransaction
    extra = 0
    fields = (
       'date_saved',
        'amount',
        'receipt_number',
        'cumulative_total',
        'fully_covered_weeks',        
        'next_week',
        'remaining_balance',
    )
    readonly_fields = (
        'amount',
        'cumulative_total',
        'fully_covered_weeks',
        'next_week',
        'remaining_balance',
        'date_saved',
    )
    
    can_delete = False
    show_change_link = True
    ordering = ['-date_saved']


# SavingsTransaction Admin
@admin.register(SavingsTransaction)
class SavingsTransactionAdmin(admin.ModelAdmin):
    list_display = ('user_profile', 'formatted_amount', 'receipt_number', 'formatted_weeks', 
                   'formatted_next_week', 'formatted_balance', 'date_saved')
    
    list_filter = ('date_saved', 'user_profile__user__is_active')
    
    search_fields = (
    'user_profile__user__username',
    'user_profile__user__first_name',
    'user_profile__user__last_name',
    'user_profile__user__email',
    )

    
    date_hierarchy = 'date_saved'
    
    autocomplete_fields = ('user_profile',)
    
    readonly_fields = ('cumulative_total', 'fully_covered_weeks', 'next_week', 
                      'remaining_balance')

    def formatted_amount(self, obj):
        return f"UGX {obj.amount:,.0f}" if obj.amount else "UGX 0"
    formatted_amount.short_description = 'Amount Saved'

    def formatted_weeks(self, obj):
        if not obj.fully_covered_weeks:
            return "No weeks fully covered"
        weeks = ", ".join(map(str, obj.fully_covered_weeks))
        return f"Weeks: {weeks}"
    formatted_weeks.short_description = "Weeks Covered"

    def formatted_next_week(self, obj):
        return f"Week {obj.next_week}"
    formatted_next_week.short_description = "Next Week"

    def formatted_balance(self, obj):
        return f"UGX {float(obj.remaining_balance):,.0f}"
    formatted_balance.short_description = "Balance Forward"

    fieldsets = (
        ('Basic Information', {
            'fields': ('user_profile', 'amount', 'receipt_number')
        }),
        ('Progress Details', {
            'fields': ('date_saved', 'cumulative_total', 'fully_covered_weeks', 
                      'next_week', 'remaining_balance')
        })
    )

    def save_model(self, request, obj, form, change):
        # Always recalculate everything from scratch
        from .models import SavingsTransaction
        from .views import evaluate_deposit, get_weekly_targets

        # Recalculate all transactions in ascending order by date_saved
        previous_transactions = SavingsTransaction.objects.filter(
            user_profile=obj.user_profile
        ).exclude(pk=obj.pk).order_by('date_saved')


        cumulative_total = 0
        carry_forward = 0
        current_week = 1

        # Recalculate all prior transactions first
        for txn in previous_transactions:
            result = evaluate_deposit(txn.amount, current_week, carry_forward)
            cumulative_total += txn.amount
            txn.fully_covered_weeks = result['fully_covered_weeks']
            txn.next_week = result['next_week']
            txn.remaining_balance = result['remaining_balance']
            txn.cumulative_total = cumulative_total
            carry_forward = float(txn.remaining_balance)
            current_week = result['next_week']
            txn.save()

        # Now calculate for the current (new or edited) transaction
        result = evaluate_deposit(obj.amount, current_week, carry_forward)
        cumulative_total += obj.amount
        obj.fully_covered_weeks = result['fully_covered_weeks']
        obj.next_week = result['next_week']
        obj.remaining_balance = result['remaining_balance']
        obj.cumulative_total = cumulative_total

        super().save_model(request, obj, form, change)


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ('user_profile', 'amount_invested', 'interest_rate', 'maturity_months', 'date_invested', 'maturity_date', 'interest_expected', 'interest_gained_so_far')
    list_filter = ('date_invested', 'maturity_months')
    search_fields = (
    'user_profile__user__username',
    'user_profile__user__first_name',
    'user_profile__user__last_name',
    'user_profile__user__email',
    )

    autocomplete_fields = ('user_profile',)


# Inline to assign members to a club while adding/editing the club
class ClubMembershipInline(admin.TabularInline):
    model = ClubMembership
    extra = 0  # Don't show extra blank forms
    fields = ('user_profile', 'is_active', 'role', 'joined_on')
    autocomplete_fields = ['user_profile']  # Improve performance on large user lists
    
    def get_queryset(self, request):
        # Only show memberships that have a user_profile
        return super().get_queryset(request).filter(user_profile__isnull=False)


@admin.register(ClubFixedSavings)
class ClubFixedSavingsAdmin(admin.ModelAdmin):
    change_form_template = "admin/change_form.html"  # Use default Django admin template
    
    list_display = [
        'club',
        'amount_fixed',
        'receipt_number',
        'interest_rate',
        'maturity_months',
        'date_fixed',
        'maturity_date',
        'expected_interest',
        'status',
        'is_active',
    ]

    list_filter = ['club', 'is_active', 'date_fixed', 'interest_rate']
    search_fields = ['club__name', 'receipt_number']

    # ✅ These are properties, so include them here:
    readonly_fields = [
        'maturity_date',
        'expected_interest',
        'interest_gained_so_far',
        'status',
        'created_at',
    ]

    # ✅ Only include model fields here — not properties unless they are also in readonly_fields
    fieldsets = (
        ('Basic Information', {
            'fields': ('club', 'amount_fixed', 'receipt_number', 'interest_rate', 'maturity_months', 'date_fixed')
        }),
        ('Calculated Fields', {
            'fields': ('maturity_date', 'expected_interest', 'interest_gained_so_far', 'status'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'created_by', 'created_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ClubFixedSavingsInline(admin.TabularInline):
    model = ClubFixedSavings
    extra = 0
    readonly_fields = ['maturity_date', 'expected_interest', 'status']
    fields = ['amount_fixed', 'receipt_number', 'interest_rate', 'maturity_months', 'date_fixed', 'is_active']
    can_delete = True


class ClubEventInline(admin.TabularInline):
    model = ClubEvent
    extra = 0
    fields = ['title', 'event_date', 'location', 'description', 'is_active']
    readonly_fields = ['created_at']
    can_delete = True


# Club admin config with inline member assignment
@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'description',
        'monthly_target',
        'get_total_savings',
        'get_active_members_count',
        'get_total_members_count',
        'last_updated'
    ]
    list_filter = ['created_at', 'monthly_target']
    search_fields = ['name', 'description']
    readonly_fields = ['last_updated', 'created_at']
    inlines = [ClubMembershipInline, ClubFixedSavingsInline, ClubEventInline]

    def get_total_savings(self, obj):
        total = ClubTransaction.objects.filter(club=obj, transaction_type='deposit').aggregate(
            total=models.Sum('amount'))['total'] or 0
        return f"UGX {total:,.0f}"
    get_total_savings.short_description = 'Total Savings'

    def get_active_members_count(self, obj):
        return ClubMembership.objects.filter(club=obj, is_active=True).count()
    get_active_members_count.short_description = 'Active Members'

    def get_total_members_count(self, obj):
        return ClubMembership.objects.filter(club=obj).count()
    get_total_members_count.short_description = 'Total Members'




# ClubMembership admin config for direct management of memberships
@admin.register(ClubMembership)
class ClubMembershipAdmin(admin.ModelAdmin):
    list_display = ('user_profile', 'club', 'role', 'is_active', 'joined_on')
    list_filter = ('role', 'is_active', 'club', 'joined_on')
    search_fields = (
        'user_profile__user__username',
        'user_profile__user__email',
        'club__name',
    )
    ordering = ('-joined_on',)
    autocomplete_fields = ['user_profile', 'club']


# ClubTransaction admin config
@admin.register(ClubTransaction)
class ClubTransactionAdmin(admin.ModelAdmin):
    list_display = ('club', 'user_profile', 'receipt_number', 'amount', 'transaction_type', 'created_at')
    list_filter = ('transaction_type', 'club', 'created_at')
    search_fields = (
        'user_profile__user__username',
        'user_profile__user__email',
        'club__name',
        'receipt_number',
        'notes',
    )
    ordering = ('-created_at',)
    autocomplete_fields = ['user_profile', 'club']


# ClubEvent admin config
@admin.register(ClubEvent)
class ClubEventAdmin(admin.ModelAdmin):
    list_display = ('club', 'title', 'event_date', 'location', 'status', 'is_active', 'created_at')
    list_filter = ('club', 'event_date', 'is_active', 'created_at')
    search_fields = (
        'title',
        'description',
        'location',
        'club__name',
    )
    ordering = ('event_date',)
    autocomplete_fields = ['club']
    readonly_fields = ['created_at', 'status']
    
    fieldsets = (
        ('Event Information', {
            'fields': ('club', 'title', 'event_date', 'location', 'description')
        }),
        ('Status', {
            'fields': ('is_active', 'created_by', 'created_at', 'status'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by for new events
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


admin.site.register(Project)


@admin.register(IndividualUserFixedSavings)
class IndividualUserFixedSavingsAdmin(admin.ModelAdmin):
    list_display = [
        'user_profile',
        'account_number',
        'principal_amount',
        'interest_rate',
        'maturity_period',
        'date_fixed',
        'maturity_date',
        'expected_interest',
        'interest_earned_so_far',
        'account_status',
        'transaction_type',
        'is_active',
        'days_remaining',
    ]
    
    list_filter = [
        'account_status',
        'transaction_type',
        'is_active',
        'maturity_period',
        'compounding_frequency',
        'maturity_option',
        'date_fixed',
        'interest_rate',
    ]
    
    search_fields = [
        'user_profile__user__username',
        'user_profile__user__first_name',
        'user_profile__user__last_name',
        'user_profile__user__email',
        'account_number',
        'notes',
    ]
    
    autocomplete_fields = ['user_profile']
    
    readonly_fields = [
        'account_number',
        'maturity_date',
        'expected_interest',
        'matured_amount',
        'interest_earned_so_far',
        'current_balance',
        'days_elapsed',
        'days_remaining',
        'interest_rate_per_day',
        'maturity_status',
        'progress_percentage',
        'created_at',
        'updated_at',
    ]
    
    fieldsets = (
        ('Account Information', {
            'fields': ('user_profile', 'account_number', 'account_status', 'transaction_type', 'is_active')
        }),
        ('Investment Details', {
            'fields': ('principal_amount', 'interest_rate', 'maturity_period', 'date_fixed', 'maturity_date', 'compounding_frequency')
        }),
        ('Financial Tracking', {
            'fields': ('expected_interest', 'interest_earned_so_far', 'matured_amount', 'current_balance'),
            'classes': ('collapse',)
        }),
        ('Maturity Management', {
            'fields': ('maturity_option', 'reinvestment_amount', 'withdrawal_amount'),
            'classes': ('collapse',)
        }),
        ('Transaction History', {
            'fields': ('last_interest_credit_date', 'total_interest_credited', 'tax_paid', 'net_interest'),
            'classes': ('collapse',)
        }),
        ('Calculated Fields', {
            'fields': ('days_elapsed', 'days_remaining', 'interest_rate_per_day', 'maturity_status', 'progress_percentage'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def days_remaining(self, obj):
        return f"{obj.days_remaining} days"
    days_remaining.short_description = 'Days Remaining'
    
    def formatted_principal_amount(self, obj):
        return f"UGX {obj.principal_amount:,.2f}" if obj.principal_amount else "UGX 0.00"
    formatted_principal_amount.short_description = 'Principal Amount'
    
    def formatted_expected_interest(self, obj):
        return f"UGX {obj.expected_interest:,.2f}" if obj.expected_interest else "UGX 0.00"
    formatted_expected_interest.short_description = 'Expected Interest'
    
    def formatted_interest_earned(self, obj):
        return f"UGX {obj.interest_earned_so_far:,.2f}" if obj.interest_earned_so_far else "UGX 0.00"
    formatted_interest_earned.short_description = 'Interest Earned'
    
    def save_model(self, request, obj, form, change):
        # Auto-calculate interest earned so far before saving
        obj.interest_earned_so_far = obj.calculate_interest_earned_so_far()
        # Calculate current balance (principal + interest earned so far)
        obj.current_balance = obj.principal_amount + obj.interest_earned_so_far
        super().save_model(request, obj, form, change)
    
    actions = ['mark_as_matured', 'mark_as_closed', 'recalculate_interest']
    
    def mark_as_matured(self, request, queryset):
        updated = queryset.update(account_status='matured')
        self.message_user(request, f'{updated} fixed savings account(s) marked as matured.')
    mark_as_matured.short_description = "Mark selected accounts as matured"
    
    def mark_as_closed(self, request, queryset):
        updated = queryset.update(account_status='closed', is_active=False)
        self.message_user(request, f'{updated} fixed savings account(s) marked as closed.')
    mark_as_closed.short_description = "Mark selected accounts as closed"
    
    def recalculate_interest(self, request, queryset):
        for obj in queryset:
            obj.interest_earned_so_far = obj.calculate_interest_earned_so_far()
            obj.save()
        self.message_user(request, f'Interest recalculated for {queryset.count()} account(s).')
    recalculate_interest.short_description = "Recalculate interest for selected accounts"


# Commercial Goat Farming Admin
@admin.register(GoatFarmingPackage)
class GoatFarmingPackageAdmin(admin.ModelAdmin):
    list_display = ['name', 'total_package_amount', 'number_of_female_goats', 'number_of_male_goats', 'expected_offspring_in_one_year', 'management_fee', 'management_fee_goat_count', 'is_active']
    list_filter = ['is_active', 'breeding_period_months']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at', 'total_initial_goats', 'expected_total_after_one_year', 'management_fee_per_goat']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Package Information', {
            'fields': ('name', 'description', 'is_active')
        }),
        ('Investment Details', {
            'fields': ('total_package_amount',)
        }),
        ('Initial Goats Provided', {
            'fields': ('number_of_female_goats', 'number_of_male_goats', 'total_initial_goats')
        }),
        ('Expected Returns', {
            'fields': ('expected_offspring_in_one_year', 'expected_total_after_one_year', 'breeding_period_months')
        }),
        ('Management Fee Structure', {
            'fields': ('management_fee', 'management_fee_goat_count', 'management_fee_per_goat')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(GoatFarmingInvestment)
class GoatFarmingInvestmentAdmin(admin.ModelAdmin):
    list_display = ['user_profile', 'package', 'investment_amount', 'start_date', 'expected_completion_date', 'status', 'initial_goats_received', 'offspring_received', 'total_goats_current', 'total_progress_percentage']
    list_filter = ['status', 'start_date', 'package']
    search_fields = ['user_profile__user__username', 'user_profile__full_name', 'package__name']
    readonly_fields = ['created_at', 'updated_at', 'days_elapsed', 'days_remaining', 'progress_percentage', 'expected_initial_goats', 'expected_offspring', 'expected_total_goats', 'goats_received_percentage', 'offspring_percentage', 'total_progress_percentage', 'expected_completion_date', 'breeding_period_months']
    date_hierarchy = 'start_date'
    
    fieldsets = (
        ('Investment Information', {
            'fields': ('user_profile', 'package', 'investment_amount', 'status')
        }),
        ('Timeline', {
            'fields': ('start_date', 'breeding_period_months', 'expected_completion_date', 'days_elapsed', 'days_remaining', 'progress_percentage')
        }),
        ('Expected Goats', {
            'fields': ('expected_initial_goats', 'expected_offspring', 'expected_total_goats')
        }),
        ('Goat Tracking', {
            'fields': ('initial_goats_received', 'offspring_received', 'total_goats_current')
        }),
        ('Progress Tracking', {
            'fields': ('goats_received_percentage', 'offspring_percentage', 'total_progress_percentage')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Goat)
class GoatAdmin(admin.ModelAdmin):
    list_display = ['goat_id', 'investment', 'gender', 'breed', 'health_status', 'is_pregnant', 'expected_delivery_date', 'date_received']
    list_filter = ['gender', 'health_status', 'is_pregnant', 'date_received', 'investment__package']
    search_fields = ['goat_id', 'breed', 'investment__user_profile__user__username']
    readonly_fields = ['goat_id', 'created_at', 'updated_at']
    date_hierarchy = 'date_received'
    
    fieldsets = (
        ('Goat Information', {
            'fields': ('goat_id', 'investment', 'gender', 'breed')
        }),
        ('Health & Status', {
            'fields': ('health_status', 'weight_kg', 'age_months')
        }),
        ('Breeding Information', {
            'fields': ('is_pregnant', 'expected_delivery_date')
        }),
        ('Timeline', {
            'fields': ('date_received', 'created_at', 'updated_at')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )


@admin.register(GoatHealthRecord)
class GoatHealthRecordAdmin(admin.ModelAdmin):
    list_display = ['goat', 'date', 'health_status', 'weight_kg', 'veterinarian', 'cost']
    list_filter = ['health_status', 'date', 'goat__investment__package']
    search_fields = ['goat__goat_id', 'veterinarian', 'symptoms', 'treatment']
    readonly_fields = ['created_at']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('Health Record', {
            'fields': ('goat', 'date', 'health_status', 'weight_kg')
        }),
        ('Medical Details', {
            'fields': ('symptoms', 'treatment', 'veterinarian', 'cost')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(GoatOffspring)
class GoatOffspringAdmin(admin.ModelAdmin):
    list_display = ['offspring_id', 'mother', 'father', 'gender', 'birth_date', 'weight_at_birth', 'is_alive']
    list_filter = ['gender', 'birth_date', 'is_alive', 'mother__investment__package']
    search_fields = ['offspring_id', 'mother__goat_id', 'father__goat_id']
    readonly_fields = ['offspring_id', 'created_at']
    date_hierarchy = 'birth_date'
    
    fieldsets = (
        ('Offspring Information', {
            'fields': ('offspring_id', 'mother', 'father', 'gender')
        }),
        ('Birth Details', {
            'fields': ('birth_date', 'weight_at_birth', 'is_alive')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(GoatFarmingTransaction)
class GoatFarmingTransactionAdmin(admin.ModelAdmin):
    list_display = ['investment', 'transaction_type', 'amount', 'status', 'due_date', 'processed_date', 'created_at']
    list_filter = ['transaction_type', 'status', 'due_date', 'processed_date', 'investment__package']
    search_fields = ['investment__user_profile__user__username', 'description', 'reference_number']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('investment', 'transaction_type', 'amount', 'description')
        }),
        ('Status & Processing', {
            'fields': ('status', 'reference_number', 'due_date', 'processed_date', 'processed_by')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(ManagementFeeTier)
class ManagementFeeTierAdmin(admin.ModelAdmin):
    list_display = ['tier_name', 'min_goats', 'max_goats', 'annual_fee', 'is_active']
    list_filter = ['is_active']
    search_fields = ['tier_name', 'description']
    readonly_fields = ['created_at']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Tier Information', {
            'fields': ('tier_name', 'description', 'is_active')
        }),
        ('Goat Requirements', {
            'fields': ('min_goats', 'max_goats')
        }),
        ('Fee Structure', {
            'fields': ('annual_fee',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(GoatFarmingNotification)
class GoatFarmingNotificationAdmin(admin.ModelAdmin):
    list_display = ['user_profile', 'notification_type', 'title', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['user_profile__user__username', 'title', 'message']
    readonly_fields = ['created_at']
    list_editable = ['is_read']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Notification Information', {
            'fields': ('user_profile', 'notification_type', 'title', 'message')
        }),
        ('Status', {
            'fields': ('is_read',)
        }),
        ('Related Objects', {
            'fields': ('related_goat', 'related_investment'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
