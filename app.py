from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Transaction, UserSettings
from config import Config
from datetime import datetime, timedelta
import csv
from io import StringIO

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()

# ==================== Routes ====================

# Authentication Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash('Welcome back to FinWise!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm')
        
        if not all([name, email, password, confirm]):
            flash('Please fill in all fields', 'error')
            return render_template('signup.html')
        
        if password != confirm:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('signup.html')
        
        user = User(name=name, email=email)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        # Create default settings
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)
        db.session.commit()
        
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

# Main Application Routes
@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's transactions
    transactions = Transaction.query.filter_by(user_id=current_user.id).all()
    
    # Calculate metrics
    total_spent = sum(t.amount for t in transactions)
    
    # Get transactions from last 30 days
    thirty_days_ago = datetime.now() - timedelta(days=30)
    recent_transactions = [t for t in transactions if t.date >= thirty_days_ago.date()]
    monthly_spending = sum(t.amount for t in recent_transactions)
    
    # Category breakdown
    categories = {}
    for t in transactions:
        categories[t.category] = categories.get(t.category, 0) + t.amount
    
    # Calculate savings (mock data)
    current_balance = 10000
    savings_goal = 0.68  # 68%
    
    return render_template('dashboard.html',
                         current_balance=current_balance,
                         monthly_spending=monthly_spending,
                         savings_goal=savings_goal,
                         categories=categories)

@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    if request.method == 'POST':
        amount = float(request.form.get('amount'))
        category = request.form.get('category')
        description = request.form.get('description')
        date_str = request.form.get('date')
        
        transaction = Transaction(
            user_id=current_user.id,
            amount=amount,
            category=category,
            description=description,
            date=datetime.strptime(date_str, '%Y-%m-%d').date()
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        flash('Expense added successfully!', 'success')
        return redirect(url_for('expenses'))
    
    # Get all transactions for current user
    transactions = Transaction.query.filter_by(user_id=current_user.id)\
        .order_by(Transaction.date.desc()).all()
    
    # Calculate summary
    total_spent = sum(t.amount for t in transactions)
    highest_expense = max([t.amount for t in transactions]) if transactions else 0
    transaction_count = len(transactions)
    
    return render_template('expenses.html',
                         transactions=transactions,
                         total_spent=total_spent,
                         highest_expense=highest_expense,
                         transaction_count=transaction_count)

@app.route('/expenses/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_expense(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    
    if transaction.user_id != current_user.id:
        flash('Unauthorized action', 'error')
        return redirect(url_for('expenses'))
    
    db.session.delete(transaction)
    db.session.commit()
    
    flash('Transaction deleted successfully', 'success')
    return redirect(url_for('expenses'))

@app.route('/learn')
@login_required
def learn():
    return render_template('learn.html')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not user_settings:
        user_settings = UserSettings(user_id=current_user.id)
        db.session.add(user_settings)
        db.session.commit()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            current_user.name = request.form.get('name')
            db.session.commit()
            flash('Profile updated successfully', 'success')
        
        elif action == 'update_notifications':
            user_settings.budget_alerts = 'budget_alerts' in request.form
            user_settings.weekly_summary = 'weekly_summary' in request.form
            user_settings.security_alerts = 'security_alerts' in request.form
            db.session.commit()
            flash('Notification preferences updated', 'success')
        
        return redirect(url_for('settings'))
    
    return render_template('settings.html', user_settings=user_settings)

@app.route('/export_data')
@login_required
def export_data():
    transactions = Transaction.query.filter_by(user_id=current_user.id)\
        .order_by(Transaction.date.desc()).all()
    
    if not transactions:
        flash('No data to export', 'info')
        return redirect(url_for('expenses'))
    
    # Create CSV
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Date', 'Category', 'Description', 'Amount'])
    
    for t in transactions:
        writer.writerow([
            t.date.strftime('%Y-%m-%d'),
            t.category,
            t.description,
            f'{t.amount:.2f}'
        ])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=finwise_export_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    
    return output

# API Routes for AJAX requests
@app.route('/api/transactions')
@login_required
def api_transactions():
    transactions = Transaction.query.filter_by(user_id=current_user.id)\
        .order_by(Transaction.date.desc()).all()
    return jsonify([t.to_dict() for t in transactions])

@app.route('/api/dashboard_data')
@login_required
def api_dashboard_data():
    transactions = Transaction.query.filter_by(user_id=current_user.id).all()
    
    # Category breakdown
    categories = {}
    for t in transactions:
        categories[t.category] = categories.get(t.category, 0) + t.amount
    
    # Monthly data (last 6 months)
    months = []
    earnings = []
    spending = []
    savings = []
    
    for i in range(5, -1, -1):
        month_date = datetime.now() - timedelta(days=30*i)
        months.append(month_date.strftime('%b'))
        
        # Mock data for earnings and calculate real spending
        monthly_transactions = [t for t in transactions 
                              if t.date.month == month_date.month 
                              and t.date.year == month_date.year]
        
        month_spending = sum(t.amount for t in monthly_transactions)
        month_earnings = month_spending + (1000 + i * 100)  # Mock earnings
        month_savings = month_earnings - month_spending
        
        earnings.append(month_earnings)
        spending.append(month_spending)
        savings.append(month_savings)
    
    return jsonify({
        'categories': categories,
        'months': months,
        'earnings': earnings,
        'spending': spending,
        'savings': savings
    })

if __name__ == '__main__':
    app.run(debug=True)