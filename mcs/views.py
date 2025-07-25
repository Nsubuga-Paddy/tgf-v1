from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .models import UserProfile, SavingsTransaction, Investment, Club, ClubMembership, ClubTransaction, ClubFixedSavings, ClubEvent, IndividualUserFixedSavings
from .forms import UserForm, ProfileForm, CustomUserCreationForm
from .decorators import project_required, club_membership_required
from django.utils import timezone
from django.utils.safestring import mark_safe
import json
from django.db import models
from datetime import datetime, timedelta

def get_weekly_targets():
    """Generate list of weekly targets"""
    return [week * 10000 for week in range(1, 53)]

def evaluate_deposit(deposit, current_week, carry_forward):
    """
    Evaluate a deposit against weekly targets
    deposit: new amount being deposited
    current_week: the next week to be covered
    carry_forward: any balance from previous deposit
    """
    weekly_targets = get_weekly_targets()
    balance = deposit + carry_forward  # Add new deposit to any carried forward balance
    fully_covered = []

    # Start checking from current_week
    for i in range(current_week - 1, 52):
        target = weekly_targets[i]  # Get target for this week (week × 10,000)
        if balance >= target:
            fully_covered.append(i + 1)  # Week is fully covered
            balance -= target  # Subtract the week's target from balance
            current_week += 1  # Move to next week
        else:
            break  # Not enough balance to cover next week

    return {
        'fully_covered_weeks': fully_covered,
        'next_week': current_week,
        'remaining_balance': balance
    }

def process_user_deposit(user_profile, deposit_amount):
    latest_txn = SavingsTransaction.objects.filter(
        user_profile=user_profile
    ).order_by('-date_saved').first()

    if latest_txn:
        current_week = latest_txn.next_week
        carry_forward = float(latest_txn.remaining_balance)
        cumulative_total = float(latest_txn.cumulative_total) + deposit_amount
    else:
        current_week = 1
        carry_forward = 0
        cumulative_total = deposit_amount

    result = evaluate_deposit(deposit_amount, current_week, carry_forward)

    result.update({
        'cumulative_total': cumulative_total
    })

    return result



def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create profile with full name
            profile = user.profile
            profile.full_name = f"{user.first_name} {user.last_name}"
            profile.save()
            messages.success(request, f'Account created for {user.username}!')
            return redirect('login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'mcs/signup.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {username}!')
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'mcs/login.html')

@login_required
def home(request):
    # Get all available clubs for the club selection modal
    available_clubs = Club.objects.all()
    
    # Add member count to each club
    for club in available_clubs:
        member_count = ClubMembership.objects.filter(club=club, is_active=True).count()
        club.member_count = member_count
    
    context = {
        'available_clubs': available_clubs,
    }
    return render(request, 'mcs/home.html', context)

def logout_view(request):
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('login')

@login_required
@project_required('52 Weeks Saving Challenge')
def wsc_member_dashboard(request):
    # Get user's first name and account number
    first_name = request.user.first_name or request.user.username
    account_number = request.user.profile.account_number or "Not assigned"
    
    user_profile = request.user.profile
    
    # Get all transactions ordered by date
    transactions = SavingsTransaction.objects.filter(
        user_profile=user_profile
    ).order_by('-date_saved')
    
    # Get latest transaction for current state
    latest_txn = transactions.order_by('-next_week', '-date_saved').first()

    if latest_txn:
        total_saved = float(latest_txn.cumulative_total)
        current_week = latest_txn.next_week
        carry_forward = float(latest_txn.remaining_balance)
    else:
        total_saved = 0
        current_week = 1
        carry_forward = 0

    progress_percentage = round((total_saved / 13780000) * 100, 2)

    weekly_targets = get_weekly_targets()
    current_week_target = weekly_targets[current_week - 1] if current_week <= 52 else 0

    updated_transactions = []
    for t in transactions:
        if t.fully_covered_weeks:
            weeks_text = "Weeks: " + ", ".join(map(str, t.fully_covered_weeks))
        else:
            weeks_text = "No weeks fully covered"
        
        updated_transactions.append({
            'date_saved': t.date_saved.strftime('%b %d, %Y'),
            'amount': float(t.amount),
            'receipt_number': t.receipt_number,
            'cumulative_total': float(t.cumulative_total),
            'weeks_covered': weeks_text,
            'remaining_balance': float(t.remaining_balance)
        })

    # Get investments
    try:
        investments = Investment.objects.filter(user_profile=user_profile)
        investment_data = []
        total_invested = 0
        total_interest_expected = 0
        total_interest_gained = 0

        for inv in investments:
            invested = float(inv.amount_invested)
            expected = float(inv.interest_expected)
            gained = float(inv.interest_gained_so_far)

            # Calculate status based on maturity date
            today = timezone.now().date()
            if today >= inv.maturity_date:
                status = 'matured'
            else:
                status = 'active'

            investment_data.append({
                'date': inv.date_invested.strftime('%b %d, %Y'),
                'amount': invested,
                'rate': inv.interest_rate,
                'interest_so_far': gained,
                'expected_interest': expected,
                'maturity_date': inv.maturity_date.strftime('%b %d, %Y'),
                'status': status
            })

            total_invested += invested
            total_interest_expected += expected
            total_interest_gained += gained
    except Exception as e:
        # If Investment model doesn't exist or there's an error, use default values
        investment_data = []
        total_invested = 0
        total_interest_expected = 0
        total_interest_gained = 0

    available_balance = total_saved - total_invested

    # Calculate progress width for progress bar
    if total_invested > 0:
        progress_width = round((available_balance / total_invested) * 100, 2)
    else:
        progress_width = 0

    context = {
        'first_name': first_name,
        'account_number': account_number,
        'savings_data': {
            'total_saved': total_saved,
            'current_week': current_week,
            'carry_forward': carry_forward,
            'target_amount': 13780000,
            'progress_percentage': progress_percentage,
            'current_week_target': current_week_target
        },
        'transactions': updated_transactions,
        'investments': investment_data,
        'investment_summary': {
            'total_invested': total_invested,
            'interest_expected': total_interest_expected,
            'interest_gained': total_interest_gained,
            'available_balance': available_balance,
            'progress_width': progress_width
        },
        'now': timezone.now(),
        'member_data_json': mark_safe(json.dumps({
            'totalSaved': total_saved,
            'currentWeek': current_week,
            'carryForward': carry_forward,
            'targetAmount': 13780000,
            'progressPercentage': progress_percentage,
            'transactions': updated_transactions,
            'investments': investment_data,
            'investmentSummary': {
                'totalInvested': total_invested,
                'interestExpected': total_interest_expected,
                'interestGained': total_interest_gained,
                'availableBalance': available_balance
            }
        }))
    }
    
    # Debug prints
    print(f"Debug - Target Amount: {context['savings_data']['target_amount']}")
    print(f"Debug - Available Balance: {context['investment_summary']['available_balance']}")
    print(f"Debug - Interest Gained: {context['investment_summary']['interest_gained']}")
    
    return render(request, 'mcs/52wsc/52wsc-member-dashboard.html', context)

#Fixed Savings Account Views
@login_required
@project_required('Fixed Savings')
def fixed_savings_terms(request):
    return render(request, 'mcs/fsa/fsa-terms.html')

@login_required
@project_required('Fixed Savings')
def individual_fixed_savings_account(request):
    from .models import IndividualUserFixedSavings
    
    # Get user's profile
    user_profile = request.user.profile
    
    # Get all fixed savings for the user
    fixed_savings = IndividualUserFixedSavings.objects.filter(
        user_profile=user_profile,
        is_active=True
    ).order_by('-date_fixed')
    
    # Calculate summary data across ALL fixed savings
    total_fixed_amount = sum(fs.principal_amount for fs in fixed_savings)
    total_expected_interest = sum(fs.expected_interest for fs in fixed_savings)
    total_interest_earned = sum(fs.interest_earned_so_far for fs in fixed_savings)
    total_matured_amount = sum(fs.matured_amount for fs in fixed_savings)
    
    # Get the most recent active fixed savings (for current account display)
    current_fixed_saving = fixed_savings.first()
    
    # Get the earliest maturing account for maturity information
    earliest_maturing = fixed_savings.filter(
        maturity_date__gte=timezone.now().date()
    ).order_by('maturity_date').first()
    
    # If no future maturing accounts, get the most recent matured account
    if not earliest_maturing:
        earliest_maturing = fixed_savings.order_by('-maturity_date').first()
    
    # Get current fixed saving details for dashboard display
    if current_fixed_saving:
        dashboard_data = {
            'account_number': current_fixed_saving.account_number,
            'principal_amount': total_fixed_amount,  # Show total across all accounts
            'matured_amount': total_matured_amount,  # Show total across all accounts
            'expected_interest': total_expected_interest,  # Show total across all accounts
            'interest_earned_so_far': total_interest_earned,  # Show total across all accounts
            'interest_rate': earliest_maturing.interest_rate if earliest_maturing else current_fixed_saving.interest_rate,
            'maturity_date': earliest_maturing.maturity_date if earliest_maturing else None,
            'days_remaining': earliest_maturing.days_remaining if earliest_maturing else 0,
            'date_fixed': earliest_maturing.date_fixed if earliest_maturing else None,
            'maturity_period': earliest_maturing.maturity_period if earliest_maturing else 0,
            'compounding_frequency': current_fixed_saving.compounding_frequency,
            'maturity_option': current_fixed_saving.maturity_option,
            'account_status': current_fixed_saving.account_status,
            'days_elapsed': earliest_maturing.days_elapsed if earliest_maturing else current_fixed_saving.days_elapsed,
            'progress_percentage': earliest_maturing.progress_percentage if earliest_maturing else current_fixed_saving.progress_percentage,
            'tax_paid': current_fixed_saving.tax_paid,
            'net_interest': current_fixed_saving.net_interest,
        }
    else:
        # Default values if no fixed savings exist
        dashboard_data = {
            'account_number': user_profile.account_number,
            'principal_amount': 0,
            'matured_amount': 0,
            'expected_interest': 0,
            'interest_earned_so_far': 0,
            'interest_rate': 0,
            'maturity_date': None,
            'days_remaining': 0,
            'date_fixed': None,
            'maturity_period': 0,
            'compounding_frequency': 'monthly',
            'maturity_option': 'withdraw',
            'account_status': 'active',
            'days_elapsed': 0,
            'progress_percentage': 0,
            'tax_paid': 0,
            'net_interest': 0,
        }
    
    # Prepare fixed savings records for the table
    fixed_savings_records = []
    for fs in fixed_savings:
        total_maturing_amount = fs.principal_amount + fs.expected_interest
        fixed_savings_records.append({
            'date': fs.date_fixed.strftime('%b %d, %Y'),
            'fixed_amount': fs.principal_amount,
            'total_maturing': total_maturing_amount,
            'expected_interest': fs.expected_interest,
            'interest_earned_so_far': fs.interest_earned_so_far,
            'interest_rate': f"{fs.interest_rate}% p.a.",
            'period': f"{fs.maturity_period} Months",
            'maturity_date': fs.maturity_date.strftime('%b %d, %Y'),
            'status': fs.account_status.title(),
            'days_remaining': fs.days_remaining,
        })
    
    # Prepare transaction records for ALL fixed savings accounts
    transaction_records = []
    running_balance = 0
    
    # Sort fixed savings by date to show transactions chronologically
    sorted_fixed_savings = fixed_savings.order_by('date_fixed')
    
    for fs in sorted_fixed_savings:
        # Add account opening transaction
        running_balance += fs.principal_amount
        transaction_records.append({
            'date': fs.date_fixed.strftime('%b %d, %Y'),
            'description': f'Fixed Savings Deposit - {fs.maturity_period} months at {fs.interest_rate}%',
            'type': 'Deposit',
            'amount': f"UGX{fs.principal_amount:,.2f}",
            'balance': f"UGX{running_balance:,.2f}"
        })
        
        # Add interest credit transaction if there's earned interest
        if fs.interest_earned_so_far > 0:
            running_balance += fs.interest_earned_so_far
            transaction_records.append({
                'date': timezone.now().strftime('%b %d, %Y'),
                'description': f'Interest Credit - {fs.maturity_period} months',
                'type': 'Credit',
                'amount': f"+UGX{fs.interest_earned_so_far:,.2f}",
                'balance': f"UGX{running_balance:,.2f}"
            })
        
        # Add tax deduction if applicable
        if fs.tax_paid > 0:
            running_balance -= fs.tax_paid
            transaction_records.append({
                'date': timezone.now().strftime('%b %d, %Y'),
                'description': 'Tax Deduction',
                'type': 'Debit',
                'amount': f"-UGX{fs.tax_paid:,.2f}",
                'balance': f"UGX{running_balance:,.2f}"
            })
    
    # Calculate summary statistics
    summary_stats = {
        'total_fixed_amount': total_fixed_amount,
        'total_expected_interest': total_expected_interest,
        'total_interest_earned': total_interest_earned,
        'total_matured_amount': total_matured_amount,
        'active_investments': fixed_savings.count(),
        'matured_investments': IndividualUserFixedSavings.objects.filter(
            user_profile=user_profile,
            account_status='matured'
        ).count(),
    }
    
    context = {
        'dashboard_data': dashboard_data,
        'fixed_savings_records': fixed_savings_records,
        'transaction_records': transaction_records,
        'summary_stats': summary_stats,
        'user_profile': user_profile,
    }
    
    return render(request, 'mcs/fsa/fsa.html', context)

#Commercial Goat Farming Views
@login_required
@project_required('Goat Farming')
def goat_farm_dashboard(request):
    from .models import GoatFarmingInvestment, Goat, GoatFarmingTransaction, GoatFarmingPackage, GoatOffspring
    
    # Get user's investments
    user_investments = GoatFarmingInvestment.objects.filter(
        user_profile__user=request.user,
        status='active'
    ).select_related('package')
    
    # Calculate total investment amount from both investments and transactions
    total_investment_from_investments = sum(investment.investment_amount for investment in user_investments)
    
    # Get all completed and pending transactions for this user
    user_transactions = GoatFarmingTransaction.objects.filter(
        investment__user_profile__user=request.user,
        status__in=['completed', 'pending']
    ).select_related('investment')
    
    # Calculate total from transactions (payments, management fees, etc.)
    total_from_transactions = sum(transaction.amount for transaction in user_transactions)
    
    # Total investment = initial investment + all transactions (completed and pending)
    total_investment = total_investment_from_investments + total_from_transactions
    
    # Calculate total package amounts (what user should pay)
    total_package_amounts = sum(
        investment.package.total_package_amount 
        for investment in user_investments 
        if investment.package
    )
    
    # Calculate pending payments (total package amount - what user has paid)
    total_pending_amount = total_package_amounts - total_investment
    
    # Get pending payment transactions for display
    pending_payments = GoatFarmingTransaction.objects.filter(
        investment__user_profile__user=request.user,
        status='pending'
    ).select_related('investment')
    
    # Calculate initial goats from packages using package data
    total_initial_female_goats = sum(
        investment.package.number_of_female_goats 
        for investment in user_investments 
        if investment.package
    )
    total_initial_male_goats = sum(
        investment.package.number_of_male_goats 
        for investment in user_investments 
        if investment.package
    )
    total_initial_goats = total_initial_female_goats + total_initial_male_goats
    
    # Calculate offspring received
    total_offspring_received = sum(
        investment.offspring_received 
        for investment in user_investments
    )
    
    # Total goats = initial goats from packages + offspring
    total_goats = total_initial_goats + total_offspring_received
    
    # Get all goats for this user (both initial and offspring)
    user_goats = Goat.objects.filter(
        investment__user_profile__user=request.user
    ).select_related('investment')
    
    # Get offspring records
    user_offspring = GoatOffspring.objects.filter(
        mother__investment__user_profile__user=request.user
    ).select_related('mother', 'father')
    
    # Calculate goat statistics (from actual goat records)
    female_goats = user_goats.filter(gender='female').count()
    male_goats = user_goats.filter(gender='male').count()
    
    # Health status counts
    healthy_goats = user_goats.filter(health_status='healthy').count()
    under_observation_goats = user_goats.filter(health_status='under_observation').count()
    sick_goats = user_goats.filter(health_status='sick').count()
    
    # Pregnant goats
    pregnant_goats = user_goats.filter(is_pregnant=True)
    
    # Calculate expected returns from packages
    total_expected_offspring = sum(
        investment.package.expected_offspring_in_one_year 
        for investment in user_investments 
        if investment.package
    )
    
    # Get the earliest expected completion date
    earliest_completion = None
    if user_investments:
        earliest_completion = min(
            investment.expected_completion_date 
            for investment in user_investments 
            if investment.expected_completion_date
        )
    
    # Get all transactions for each investment to display individually
    investment_transactions = []
    for investment in user_investments:
        # Get all transactions for this investment (both completed and pending)
        transactions = GoatFarmingTransaction.objects.filter(
            investment=investment
        ).select_related('investment', 'investment__package').order_by('created_at')
        
        # Calculate totals for this investment
        if investment.package and investment.package.total_package_amount:
            package_total = investment.package.total_package_amount
            total_paid_for_investment = investment.investment_amount + sum(
                transaction.amount for transaction in transactions.filter(status='completed')
            )
            investment.pending_balance = package_total - total_paid_for_investment
            investment.payment_progress = (total_paid_for_investment / package_total) * 100
            investment.total_paid = total_paid_for_investment
        else:
            investment.pending_balance = 0
            investment.payment_progress = 0
            investment.total_paid = investment.investment_amount
        
        # Add initial investment as first transaction
        if investment.investment_amount > 0:
            investment_transactions.append({
                'investment': investment,
                'transaction_type': 'Initial Investment',
                'amount': investment.investment_amount,
                'status': 'completed',
                'date': investment.start_date,
                'description': f'Initial investment for {investment.package.name}',
                'reference_number': investment.receipt_number,
                'is_initial': True
            })
        
        # Add all other transactions
        for transaction in transactions:
            investment_transactions.append({
                'investment': investment,
                'transaction_type': transaction.get_transaction_type_display(),
                'amount': transaction.amount,
                'status': transaction.status,
                'date': transaction.created_at,
                'description': transaction.description,
                'reference_number': transaction.reference_number,
                'is_initial': False
            })
    
    context = {
        'user_investments': user_investments,
        'investment_transactions': investment_transactions,
        'total_investment': total_investment,
        'total_package_amounts': total_package_amounts,
        'total_goats': total_goats,
        'total_initial_goats': total_initial_goats,
        'total_initial_female_goats': total_initial_female_goats,
        'total_initial_male_goats': total_initial_male_goats,
        'total_offspring_received': total_offspring_received,
        'female_goats': female_goats,
        'male_goats': male_goats,
        'healthy_goats': healthy_goats,
        'under_observation_goats': under_observation_goats,
        'sick_goats': sick_goats,
        'pregnant_goats': pregnant_goats,
        'user_offspring': user_offspring,
        'total_expected_offspring': total_expected_offspring,
        'total_pending_amount': total_pending_amount,
        'earliest_completion': earliest_completion,
        'pending_payments': pending_payments,
    }
    
    return render(request, 'mcs/goat-farm/dashboard.html', context)

@login_required
@project_required('Goat Farming')
def goat_farm_investment(request):
    return render(request, 'mcs/goat-farm/investment.html')

@login_required
@project_required('Goat Farming')
def goat_farm_transactions(request):
    from .models import GoatFarmingInvestment, GoatFarmingTransaction, GoatFarmingPackage
    
    # Get user's investments
    user_investments = GoatFarmingInvestment.objects.filter(
        user_profile__user=request.user,
        status='active'
    ).select_related('package')
    
    # Calculate total investment amount (same logic as dashboard)
    total_investment_from_investments = sum(investment.investment_amount for investment in user_investments)
    
    # Get all completed and pending transactions for this user (same as dashboard)
    user_transactions = GoatFarmingTransaction.objects.filter(
        investment__user_profile__user=request.user,
        status__in=['completed', 'pending']
    ).select_related('investment', 'investment__package').order_by('-created_at')
    
    # Calculate total from transactions (same as dashboard)
    total_from_transactions = sum(transaction.amount for transaction in user_transactions)
    
    # Total investment = initial investment + all transactions (completed and pending) - same as dashboard
    total_investment = total_investment_from_investments + total_from_transactions
    
    # Calculate total package amounts (what user should pay) - same as dashboard
    total_package_amounts = sum(
        investment.package.total_package_amount 
        for investment in user_investments 
        if investment.package
    )
    
    # Calculate pending payments (total package amount - what user has paid) - same as dashboard
    total_pending_amount = total_package_amounts - total_investment
    
    # Calculate allocation of deposits: first to goats (600,000 per goat), then to management fees
    GOAT_COST = 600000  # Cost per goat in UGX
    
    # Get all payment and management fee transactions (both completed and pending)
    payment_transactions = user_transactions.filter(transaction_type__in=['payment', 'management_fee'])
    
    total_deposits = sum(transaction.amount for transaction in payment_transactions)
    
    # Calculate how many goats can be purchased with total deposits
    goats_purchasable = int(total_deposits // GOAT_COST)
    goats_purchased = min(goats_purchasable, 10)  # Limit to 10 goats maximum
    
    # Calculate amount allocated to goats
    amount_for_goats = goats_purchased * GOAT_COST
    
    # Calculate amount remaining for management fees
    amount_for_management_fees = total_deposits - amount_for_goats
    
    # Calculate totals by transaction type for display
    total_investments = sum(
        transaction.amount for transaction in user_transactions 
        if transaction.transaction_type == 'investment'
    )
    
    # Use calculated management fees instead of actual transaction amounts
    total_management_fees = amount_for_management_fees
    
    total_returns = sum(
        transaction.amount for transaction in user_transactions 
        if transaction.transaction_type == 'returns'
    )
    
    total_pending_payments = sum(
        transaction.amount for transaction in user_transactions 
        if transaction.status == 'pending'
    )
    
    # Get investment count
    investment_count = user_investments.count()
    
    # Get management fee payment count (based on calculated allocation)
    management_fee_count = payment_transactions.count()  # Count of payment and management fee transactions
    
    # Get returns count (in goats)
    returns_count = user_transactions.filter(
        transaction_type='returns',
        status='completed'
    ).count()
    
    # Get earliest pending payment due date
    earliest_pending_due = user_transactions.filter(
        status='pending'
    ).order_by('due_date').values_list('due_date', flat=True).first()
    
    # Apply filters if provided
    transaction_type_filter = request.GET.get('type')
    status_filter = request.GET.get('status')
    start_date_filter = request.GET.get('start_date')
    end_date_filter = request.GET.get('end_date')
    
    filtered_transactions = user_transactions
    
    if transaction_type_filter:
        if transaction_type_filter == 'investment':
            filtered_transactions = filtered_transactions.filter(transaction_type='investment')
        elif transaction_type_filter == 'fee':
            filtered_transactions = filtered_transactions.filter(transaction_type='management_fee')
        elif transaction_type_filter == 'return':
            filtered_transactions = filtered_transactions.filter(transaction_type='returns')
    
    if status_filter:
        filtered_transactions = filtered_transactions.filter(status=status_filter)
    
    if start_date_filter:
        filtered_transactions = filtered_transactions.filter(created_at__date__gte=start_date_filter)
    
    if end_date_filter:
        filtered_transactions = filtered_transactions.filter(created_at__date__lte=end_date_filter)
    
    # Prepare transaction data for template
    transactions_data = []
    for transaction in filtered_transactions:
        # Determine badge color based on transaction type
        type_badge_class = {
            'investment': 'bg-primary',
            'payment': 'bg-info',
            'management_fee': 'bg-info',
            'veterinary_cost': 'bg-warning',
            'feed_cost': 'bg-warning',
            'other_expense': 'bg-secondary',
            'returns': 'bg-success'
        }.get(transaction.transaction_type, 'bg-secondary')
        
        # Determine status badge color
        status_badge_class = {
            'completed': 'bg-success',
            'pending': 'bg-warning',
            'cancelled': 'bg-danger',
            'failed': 'bg-danger'
        }.get(transaction.status, 'bg-secondary')
        
        transactions_data.append({
            'id': transaction.id,
            'date': transaction.created_at.strftime('%Y-%m-%d'),
            'receipt_no': transaction.reference_number or '-',
            'type': transaction.get_transaction_type_display(),
            'type_badge_class': type_badge_class,
            'description': transaction.description,
            'amount': transaction.amount,
            'status': transaction.get_status_display(),
            'status_badge_class': status_badge_class,
            'investment': transaction.investment,
            'due_date': transaction.due_date,
            'processed_date': transaction.processed_date,
            'processed_by': transaction.processed_by
        })
    
    # Add initial investments as transactions
    for investment in user_investments:
        if investment.investment_amount > 0:
            transactions_data.append({
                'id': f'investment_{investment.id}',
                'date': investment.start_date.strftime('%Y-%m-%d'),
                'receipt_no': investment.receipt_number or '-',
                'type': 'Initial Investment',
                'type_badge_class': 'bg-primary',
                'description': f'Initial investment for {investment.package.name}',
                'amount': investment.investment_amount,
                'status': 'Completed',
                'status_badge_class': 'bg-success',
                'investment': investment,
                'due_date': None,
                'processed_date': investment.created_at,
                'processed_by': None
            })
    
    # Sort transactions by date (newest first)
    transactions_data.sort(key=lambda x: x['date'], reverse=True)
    
    context = {
        'total_investments': total_investment,  # Use the same calculation as dashboard
        'investment_count': investment_count,
        'total_management_fees': total_management_fees,
        'management_fee_count': management_fee_count,
        'total_returns': total_returns,
        'returns_count': returns_count,
        'total_pending_payments': total_pending_payments,
        'earliest_pending_due': earliest_pending_due,
        'total_pending_amount': total_pending_amount,  # Same as dashboard
        'total_package_amounts': total_package_amounts,  # Same as dashboard
        # Returns calculator variables
        'kids_per_goat_per_year': 3,
        'market_price_per_kid': 400000,
        'transactions': transactions_data,
        'filter_type': transaction_type_filter,
        'filter_status': status_filter,
        'filter_start_date': start_date_filter,
        'filter_end_date': end_date_filter,
        # Goat allocation information
        'goats_purchased': goats_purchased,
        'amount_for_goats': amount_for_goats,
        'amount_for_management_fees': amount_for_management_fees,
        'total_deposits': total_deposits,
        'goat_cost': GOAT_COST,
    }
    
    return render(request, 'mcs/goat-farm/transactions.html', context)

@login_required
@project_required('Goat Farming')
def goat_farm_transaction_details(request, transaction_id):
    """Get transaction details for modal display"""
    from django.http import JsonResponse
    
    try:
        # Handle both regular transactions and initial investments
        if transaction_id.startswith('investment_'):
            investment_id = transaction_id.split('_')[1]
            investment = GoatFarmingInvestment.objects.get(
                id=investment_id,
                user_profile__user=request.user
            )
            
            data = {
                'id': f'investment_{investment.id}',
                'date': investment.start_date.strftime('%Y-%m-%d'),
                'type': 'Initial Investment',
                'type_color': 'primary',
                'status': 'Completed',
                'status_color': 'success',
                'amount': float(investment.investment_amount),
                'goats': None,
                'description': f'Initial investment for {investment.package.name}',
                'payment_method': 'Bank Transfer',
                'reference': investment.receipt_number or '-',
                'processed_by': '-',
                'processed_date': investment.created_at.strftime('%Y-%m-%d %H:%M'),
                'notes': investment.notes or ''
            }
        else:
            transaction = GoatFarmingTransaction.objects.get(
                id=transaction_id,
                investment__user_profile__user=request.user
            )
            
            data = {
                'id': transaction.id,
                'date': transaction.created_at.strftime('%Y-%m-%d'),
                'type': transaction.get_transaction_type_display(),
                'type_color': {
                    'investment': 'primary',
                    'payment': 'info',
                    'management_fee': 'info',
                    'veterinary_cost': 'warning',
                    'feed_cost': 'warning',
                    'other_expense': 'secondary',
                    'returns': 'success'
                }.get(transaction.transaction_type, 'secondary'),
                'status': transaction.get_status_display(),
                'status_color': {
                    'completed': 'success',
                    'pending': 'warning',
                    'cancelled': 'danger',
                    'failed': 'danger'
                }.get(transaction.status, 'secondary'),
                'amount': float(transaction.amount) if transaction.transaction_type != 'returns' else None,
                'goats': transaction.amount if transaction.transaction_type == 'returns' else None,
                'description': transaction.description,
                'payment_method': 'Bank Transfer',
                'reference': transaction.reference_number or '-',
                'processed_by': transaction.processed_by.get_full_name() if transaction.processed_by else '-',
                'processed_date': transaction.processed_date.strftime('%Y-%m-%d %H:%M') if transaction.processed_date else '-',
                'notes': transaction.notes or ''
            }
        
        return JsonResponse(data)
        
    except (GoatFarmingInvestment.DoesNotExist, GoatFarmingTransaction.DoesNotExist):
        return JsonResponse({'error': 'Transaction not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@project_required('Goat Farming')
def goat_farm_performance(request):
    return render(request, 'mcs/goat-farm/performance.html')

@login_required
@project_required('Goat Farming')
def goat_farm_tracking(request):
    """Visual tracking page for farm activities using satellite imagery"""
    from .models import GoatFarmingInvestment, Goat, GoatFarmingTransaction, GoatHealthRecord, GoatOffspring
    
    # Get user's investments and related data
    user_investments = GoatFarmingInvestment.objects.filter(
        user_profile__user=request.user,
        status='active'
    ).select_related('package')
    
    # Get all goats for this user
    user_goats = Goat.objects.filter(
        investment__user_profile__user=request.user
    ).select_related('investment', 'investment__package')
    
    # Get recent health records
    recent_health_records = GoatHealthRecord.objects.filter(
        goat__investment__user_profile__user=request.user
    ).select_related('goat').order_by('-date')[:10]
    
    # Get recent offspring
    recent_offspring = GoatOffspring.objects.filter(
        mother__investment__user_profile__user=request.user
    ).select_related('mother', 'father').order_by('-birth_date')[:5]
    
    # Get recent transactions
    recent_transactions = GoatFarmingTransaction.objects.filter(
        investment__user_profile__user=request.user
    ).select_related('investment').order_by('-created_at')[:10]
    
    # Calculate farm statistics
    total_goats = user_goats.count()
    healthy_goats = user_goats.filter(health_status='healthy').count()
    pregnant_goats = user_goats.filter(is_pregnant=True).count()
    total_offspring = recent_offspring.count()
    
    # Prepare farm activity timeline
    farm_activities = []
    
    # Add health records to timeline
    for record in recent_health_records:
        farm_activities.append({
            'date': record.date,
            'type': 'health',
            'title': f'Health Check - {record.goat.goat_id}',
            'description': f'{record.goat.goat_id} status: {record.get_health_status_display()}',
            'icon': 'stethoscope',
            'color': 'info',
            'goat': record.goat
        })
    
    # Add offspring births to timeline
    for offspring in recent_offspring:
        farm_activities.append({
            'date': offspring.birth_date,
            'type': 'birth',
            'title': f'New Offspring - {offspring.offspring_id}',
            'description': f'New {offspring.gender} kid born to {offspring.mother.goat_id}',
            'icon': 'baby',
            'color': 'success',
            'goat': offspring.mother
        })
    
    # Add transactions to timeline
    for transaction in recent_transactions:
        farm_activities.append({
            'date': transaction.created_at.date(),
            'type': 'transaction',
            'title': f'{transaction.get_transaction_type_display()} - UGX {transaction.amount:,.0f}',
            'description': transaction.description,
            'icon': 'money-bill',
            'color': 'primary',
            'transaction': transaction
        })
    
    # Sort activities by date (newest first)
    farm_activities.sort(key=lambda x: x['date'], reverse=True)
    
    # Prepare satellite imagery data (mock data for now)
    satellite_data = {
        'last_updated': timezone.now(),
        'coverage_area': '2.5 acres',
        'resolution': 'High (0.5m)',
        'weather_conditions': 'Clear',
        'temperature': '25°C',
        'humidity': '65%',
        'wind_speed': '12 km/h'
    }
    
    # Prepare farm zones for satellite overlay
    farm_zones = []
    for investment in user_investments:
        if investment.package:
            farm_zones.append({
                'name': f'Zone {investment.id}',
                'package': investment.package.name,
                'goats_count': user_goats.filter(investment=investment).count(),
                'area': '0.5 acres',
                'coordinates': f'Zone {investment.id} coordinates',
                'status': 'Active'
            })
    
    context = {
        'user_investments': user_investments,
        'user_goats': user_goats,
        'recent_health_records': recent_health_records,
        'recent_offspring': recent_offspring,
        'recent_transactions': recent_transactions,
        'farm_activities': farm_activities[:20],  # Limit to 20 most recent
        'satellite_data': satellite_data,
        'farm_zones': farm_zones,
        'total_goats': total_goats,
        'healthy_goats': healthy_goats,
        'pregnant_goats': pregnant_goats,
        'total_offspring': total_offspring,
    }
    
    return render(request, 'mcs/goat-farm/tracking.html', context)

#Clubs Views
@login_required
@project_required('Clubs Savings')
@club_membership_required
def clubs_dashboard(request, club_id=None):
    from .models import Club, ClubTransaction, ClubMembership, ClubFixedSavings
    # If no club_id is provided, use the first available club or default to 1
    if club_id is None:
        first_club = Club.objects.first()
        club_id = first_club.id if first_club else 1
    
    # Get the club object
    try:
        club = Club.objects.get(id=club_id)
    except Club.DoesNotExist:
        club = None
    
    # Calculate club's total savings
    if club:
        # Get all approved deposit transactions for this club
        total_deposits = ClubTransaction.objects.filter(
            club=club,
            transaction_type='deposit'
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        # Get all approved withdrawal transactions for this club
        total_withdrawals = ClubTransaction.objects.filter(
            club=club,
            transaction_type='withdrawal'
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        # Calculate total savings (deposits - withdrawals)
        total_savings = total_deposits - total_withdrawals
        
        # Get active members count
        active_members = ClubMembership.objects.filter(
            club=club,
            is_active=True
        ).count()
        
        # Get total members count
        total_members = ClubMembership.objects.filter(club=club).count()
        
        # Get monthly target and collection
        monthly_target = club.monthly_target
        monthly_collection = club.get_monthly_collection()
        monthly_progress = club.get_monthly_progress()
        
        # Get last updated timestamp
        last_updated = club.last_updated
        
        # Get fixed savings data
        total_fixed_amount = ClubFixedSavings.objects.filter(
            club=club,
            is_active=True
        ).aggregate(total=models.Sum('amount_fixed'))['total'] or 0
        
        # Calculate total expected interest using the property
        total_expected_interest = 0
        active_fixed_savings = ClubFixedSavings.objects.filter(
            club=club,
            is_active=True
        )
        for fixed_saving in active_fixed_savings:
            total_expected_interest += float(fixed_saving.expected_interest)
        
        # Calculate available savings (total savings - fixed savings)
        available_savings = total_savings - total_fixed_amount
        
        # Calculate percentages
        if total_savings > 0:
            fixed_percentage = (total_fixed_amount / total_savings) * 100
            available_percentage = (available_savings / total_savings) * 100
        else:
            fixed_percentage = 0
            available_percentage = 0
        
        # Get fixed savings details for display
        fixed_savings_details = []
        for fixed in active_fixed_savings:
            fixed_savings_details.append({
                'receipt_number': fixed.receipt_number or 'N/A',
                'date_fixed': fixed.date_fixed.strftime('%Y-%m-%d'),
                'amount': fixed.amount_fixed,
                'interest_rate': f"{fixed.interest_rate}% p.a.",
                'maturity_date': fixed.maturity_date.strftime('%Y-%m-%d'),
                'expected_interest': fixed.expected_interest,
                'interest_gained_so_far': fixed.interest_gained_so_far,
                'status': fixed.status.title()
            })
        
        # Get recent transactions for display
        recent_transactions = ClubTransaction.objects.filter(
            club=club
        ).order_by('-created_at')[:5]  # Get last 5 transactions
        
        recent_transactions_data = []
        for txn in recent_transactions:
            # Get member name with better fallback logic
            if txn.user_profile:
                # First try UserProfile's full_name field
                if txn.user_profile.full_name and txn.user_profile.full_name.strip():
                    member_name = txn.user_profile.full_name
                # Then try User's get_full_name()
                elif txn.user_profile.user and txn.user_profile.user.get_full_name().strip():
                    member_name = txn.user_profile.user.get_full_name()
                # Then try username
                elif txn.user_profile.user and txn.user_profile.user.username:
                    member_name = txn.user_profile.user.username
                else:
                    member_name = 'Unknown Member'
            else:
                member_name = 'N/A'
            
            recent_transactions_data.append({
                'date': txn.created_at.strftime('%Y-%m-%d'),
                'member': member_name,
                'type': txn.transaction_type.title(),
                'amount': txn.amount,
                'status': 'Completed'  # Assuming all transactions are completed
            })
        
        # Prepare club information for display
        club_info = {
            'name': club.name,
            'founded': club.created_at.strftime('%B %Y'),
            'monthly_target': club.monthly_target,
            'monthly_progress_percentage': monthly_progress
        }
        
        # Get upcoming events for display
        upcoming_events = ClubEvent.objects.filter(
            club=club,
            is_active=True,
            event_date__gte=timezone.now().date()
        ).order_by('event_date')[:5]  # Get next 5 upcoming events
        
        upcoming_events_data = []
        for event in upcoming_events:
            upcoming_events_data.append({
                'title': event.title,
                'date': event.event_date.strftime('%b %d, %Y'),
                'description': event.description,
                'location': event.location,
                'status': event.status
            })
    else:
        total_savings = 0
        active_members = 0
        total_members = 0
        monthly_target = 0
        monthly_collection = 0
        monthly_progress = 0
        last_updated = timezone.now()
        total_fixed_amount = 0
        total_expected_interest = 0
        available_savings = 0
        fixed_percentage = 0
        available_percentage = 0
        fixed_savings_details = []
        recent_transactions_data = []
        club_info = {}
        upcoming_events_data = []
    
    context = {
        'default_club_id': club_id,
        'club_id': club_id,
        'club': club,
        'total_savings': total_savings,
        'active_members': active_members,
        'total_members': total_members,
        'monthly_target': monthly_target,
        'monthly_collection': monthly_collection,
        'monthly_progress': monthly_progress,
        'last_updated': last_updated,
        'total_fixed_amount': total_fixed_amount,
        'total_expected_interest': total_expected_interest,
        'available_savings': available_savings,
        'fixed_percentage': fixed_percentage,
        'available_percentage': available_percentage,
        'fixed_savings_details': fixed_savings_details,
        'recent_transactions_data': recent_transactions_data,
        'club_info': club_info,
        'upcoming_events_data': upcoming_events_data
    }
    return render(request, 'mcs/clubs/dashboard.html', context)

@login_required
@project_required('Clubs Savings')
@club_membership_required
def club_members(request, club_id):
    from .models import Club, ClubMembership, ClubTransaction, ClubFixedSavings
    from django.utils import timezone
    from django.db import models
    from datetime import datetime, timedelta
    
    # Get the club object
    try:
        club = Club.objects.get(id=club_id)
        print(f"Debug - Club found: {club.name} (ID: {club.id})")
    except Club.DoesNotExist:
        club = None
        print(f"Debug - Club not found for ID: {club_id}")
    
    if club:
        # Get total members count
        total_members = ClubMembership.objects.filter(club=club).count()
        print(f"Debug - Total members for {club.name}: {total_members}")
        
        # Get active members count
        active_members = ClubMembership.objects.filter(club=club, is_active=True).count()
        print(f"Debug - Active members for {club.name}: {active_members}")
        
        # Get active contributors (members who made transactions this month)
        current_month = timezone.now().month
        current_year = timezone.now().year
        
        active_contributors = ClubTransaction.objects.filter(
            club=club,
            transaction_type='deposit',
            created_at__year=current_year,
            created_at__month=current_month
        ).values('user_profile').distinct().count()
        print(f"Debug - Active contributors for {club.name}: {active_contributors}")
        
        # Get total fixed savings amount (not count, but total amount)
        total_fixed_amount = ClubFixedSavings.objects.filter(
            club=club,
            is_active=True
        ).aggregate(total=models.Sum('amount_fixed'))['total'] or 0
        print(f"Debug - Total fixed amount for {club.name}: {total_fixed_amount}")
        
        # Get all members with their details
        members_data = []
        memberships = ClubMembership.objects.filter(club=club).select_related('user_profile__user')
        print(f"Debug - Found {memberships.count()} memberships for {club.name}")
        
        for membership in memberships:
            # Get member's total savings
            total_savings = ClubTransaction.objects.filter(
                club=club,
                user_profile=membership.user_profile,
                transaction_type='deposit'
            ).aggregate(total=models.Sum('amount'))['total'] or 0
            
            # Get member's fixed savings
            member_fixed_savings = ClubFixedSavings.objects.filter(
                club=club,
                created_by=membership.user_profile.user,
                is_active=True
            ).aggregate(total=models.Sum('amount_fixed'))['total'] or 0
            
            # Get last contribution date
            last_contribution = ClubTransaction.objects.filter(
                club=club,
                user_profile=membership.user_profile,
                transaction_type='deposit'
            ).order_by('-created_at').first()
            
            last_contribution_date = last_contribution.created_at.strftime('%Y-%m-%d') if last_contribution else 'Never'
            
            # Get member name
            if membership.user_profile:
                if membership.user_profile.full_name and membership.user_profile.full_name.strip():
                    member_name = membership.user_profile.full_name
                elif membership.user_profile.user and membership.user_profile.user.get_full_name().strip():
                    member_name = membership.user_profile.user.get_full_name()
                elif membership.user_profile.user and membership.user_profile.user.username:
                    member_name = membership.user_profile.user.username
                else:
                    member_name = 'Unknown Member'
            else:
                member_name = 'Unknown Member'
            
            members_data.append({
                'member_id': membership.user_profile.account_number if membership.user_profile and membership.user_profile.account_number else f"M{membership.id:03d}",
                'name': member_name,
                'join_date': membership.joined_on.strftime('%Y-%m-%d'),
                'status': 'Active' if membership.is_active else 'Inactive',
                'total_savings': total_savings,
                'fixed_savings': member_fixed_savings,
                'last_contribution': last_contribution_date,
                'role': membership.role.title()
            })
        
        # Get executive committee members (those with admin role)
        executive_committee = [
            member for member in members_data 
            if member['role'] in ['Admin', 'Club Admin']
        ]
        
        # Get regular committee members (you can customize this logic)
        committee_members = [
            member for member in members_data 
            if member['role'] not in ['Admin', 'Club Admin'] and member['status'] == 'Active'
        ][:5]  # Limit to 5 committee members
        
    else:
        total_members = 0
        active_members = 0
        active_contributors = 0
        total_fixed_amount = 0
        members_data = []
        executive_committee = []
        committee_members = []
    
    context = {
        'club_id': club_id,
        'default_club_id': club_id,
        'club': club,
        'total_members': total_members,
        'active_members': active_members,
        'active_contributors': active_contributors,
        'total_fixed_amount': total_fixed_amount,
        'members_data': members_data,
        'executive_committee': executive_committee,
        'committee_members': committee_members
    }
    return render(request, 'mcs/clubs/members.html', context)

@login_required
@project_required('Clubs Savings')
@club_membership_required
def club_transactions(request, club_id):
    from .models import Club, ClubTransaction, ClubFixedSavings
    from django.utils import timezone
    from django.db import models
    from datetime import datetime, timedelta
    
    # Get the club object
    try:
        club = Club.objects.get(id=club_id)
    except Club.DoesNotExist:
        club = None
    
    if club:
        # Get total transactions count (last 30 days)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        total_transactions = ClubTransaction.objects.filter(
            club=club,
            created_at__gte=thirty_days_ago
        ).count()
        
        # Get monthly contributions and withdrawals
        current_month = timezone.now().month
        current_year = timezone.now().year
        
        monthly_contributions = ClubTransaction.objects.filter(
            club=club,
            transaction_type='deposit',
            created_at__year=current_year,
            created_at__month=current_month
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        monthly_withdrawals = ClubTransaction.objects.filter(
            club=club,
            transaction_type='withdrawal',
            created_at__year=current_year,
            created_at__month=current_month
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        # Get fixed savings data
        total_fixed_amount = ClubFixedSavings.objects.filter(
            club=club,
            is_active=True
        ).aggregate(total=models.Sum('amount_fixed'))['total'] or 0
        
        # Calculate total expected interest using the property
        total_expected_interest = 0
        active_fixed_savings = ClubFixedSavings.objects.filter(
            club=club,
            is_active=True
        )
        for fixed_saving in active_fixed_savings:
            total_expected_interest += float(fixed_saving.expected_interest)
        
        # Calculate available savings (total deposits - total withdrawals - fixed savings)
        total_deposits = ClubTransaction.objects.filter(
            club=club,
            transaction_type='deposit'
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        total_withdrawals = ClubTransaction.objects.filter(
            club=club,
            transaction_type='withdrawal'
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        available_savings = total_deposits - total_withdrawals - total_fixed_amount
        
        # Get recent transactions for the table
        recent_transactions = ClubTransaction.objects.filter(
            club=club
        ).order_by('-created_at')[:10]  # Get last 10 transactions
        
        transactions_data = []
        for txn in recent_transactions:
            # Get member name
            if txn.user_profile:
                if txn.user_profile.full_name and txn.user_profile.full_name.strip():
                    member_name = txn.user_profile.full_name
                elif txn.user_profile.user and txn.user_profile.user.get_full_name().strip():
                    member_name = txn.user_profile.user.get_full_name()
                elif txn.user_profile.user and txn.user_profile.user.username:
                    member_name = txn.user_profile.user.username
                else:
                    member_name = 'Unknown Member'
            else:
                member_name = 'N/A'
            
            transactions_data.append({
                'receipt_number': txn.receipt_number if txn.receipt_number else f"TRX-{txn.id:06d}",
                'date': txn.created_at.strftime('%Y-%m-%d'),
                'member': member_name,
                'type': txn.transaction_type.title(),
                'amount': txn.amount,
                'payment_method': 'Cash',  # Default since we don't have this field
                'status': 'Completed'  # Default since we don't have status field
            })
        
        # Get fixed savings records for the table
        fixed_savings_records = ClubFixedSavings.objects.filter(
            club=club,
            is_active=True
        ).order_by('-created_at')
        
        fixed_savings_data = []
        for fixed in fixed_savings_records:
            # Get member name
            if fixed.created_by:
                if fixed.created_by.first_name and fixed.created_by.last_name:
                    member_name = f"{fixed.created_by.first_name} {fixed.created_by.last_name}"
                elif fixed.created_by.username:
                    member_name = fixed.created_by.username
                else:
                    member_name = 'Unknown Member'
            else:
                member_name = 'N/A'
            
            fixed_savings_data.append({
                'receipt_number': fixed.receipt_number or f"FS-{fixed.id:06d}",
                'date_fixed': fixed.date_fixed.strftime('%Y-%m-%d'),
                'member': member_name,
                'amount': fixed.amount_fixed,
                'interest_rate': f"{fixed.interest_rate}% p.a.",
                'maturity_date': fixed.maturity_date.strftime('%Y-%m-%d'),
                'expected_interest': fixed.expected_interest,
                'status': fixed.status.title()
            })
        
    else:
        total_transactions = 0
        monthly_contributions = 0
        monthly_withdrawals = 0
        total_fixed_amount = 0
        total_expected_interest = 0
        available_savings = 0
        transactions_data = []
        fixed_savings_data = []
    
    context = {
        'club_id': club_id,
        'default_club_id': club_id,
        'club': club,
        'total_transactions': total_transactions,
        'monthly_contributions': monthly_contributions,
        'monthly_withdrawals': monthly_withdrawals,
        'total_fixed_amount': total_fixed_amount,
        'total_expected_interest': total_expected_interest,
        'available_savings': available_savings,
        'transactions_data': transactions_data,
        'fixed_savings_data': fixed_savings_data
    }
    return render(request, 'mcs/clubs/transactions.html', context)

# RSS Views
@login_required
@project_required('Retirement Savings Scheme')
def rss_dashboard(request):
    return render(request, 'mcs/rss/dashboard.html')

@login_required
@project_required('Retirement Savings Scheme')
def rss_portfolio(request):
    return render(request, 'mcs/rss/portfolio.html')

@login_required
@project_required('Retirement Savings Scheme')
def rss_emergency_funds(request):
    return render(request, 'mcs/rss/emergency_funds.html')


#GW Views
@login_required
@project_required('Generational Wealth')
def gw_portfolio(request):
    return render(request, 'mcs/gw/portfolio.html')

@login_required
@project_required('Generational Wealth')
def gw_savings(request):
    return render(request, 'mcs/gw/savings.html')


#User Profile Views
@login_required
def profile_view(request):
    profile = request.user.profile
    # Get user's projects (groups they have access to)
    user_projects = profile.projects.all()
    
    return render(request, 'mcs/profile/view.html', {
        'profile': profile,
        'user_projects': user_projects,
        'account_number': profile.account_number  # Use the account_number from the model
    })


@login_required
def profile_edit(request):
    user = request.user
    profile = user.profile

    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile_view')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        user_form = UserForm(instance=user)
        profile_form = ProfileForm(instance=profile)

    return render(request, 'mcs/profile/edit.html', {
        'user_form': user_form,
        'profile_form': profile_form
    })

# Support View
@login_required
def support_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Here you would typically:
        # 1. Save the message to the database
        # 2. Send an email to the support team
        # For now, we'll just show a success message
        messages.success(
            request,
            'Thank you for your message. Our support team will get back to you within 24 hours.'
        )
        return redirect('support')
    
    return render(request, 'mcs/support.html')


