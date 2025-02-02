from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
import os
import requests
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# MongoDB Connection
client = MongoClient("mongodb+srv://asanmo2004:RfQ10vkwwRg0Z5uM@cluster0.nezjf.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client.stock_market_db
users_collection = db.users
stocks_collection = db.stocks
portfolios_collection = db.portfolios
transactions_collection = db.transactions

# Alpha Vantage API Key
ALPHA_VANTAGE_API_KEY = "VK2M3FESWT5ZVQI5"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={}&apikey={}"

# Password hashing
bcrypt = Bcrypt(app)

@app.route('/')
def home():
    return render_template('home.html')

# Registration Route
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('signup'))

        if users_collection.find_one({'email': email}):
            flash('Email already exists!', 'danger')
            return redirect(url_for('signup'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        users_collection.insert_one({
            'username': username,
            'email': email,
            'password': hashed_password
        })

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = users_collection.find_one({'email': email})
        if user and bcrypt.check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard')) 
        else:
            flash('Invalid email or password!', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' in session:
        return render_template('dashboard.html', username=session['username'])
    else:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))

# Live Market Route
@app.route('/live-market')
def live_market():
    if 'username' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))
    
    stocks = list(stocks_collection.find({}, {'_id': 0}))
    return render_template('live_market.html', stocks=stocks)

# Refresh Stock Prices (API Call)
@app.route('/refresh-stocks')
def refresh_stocks():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    stock_symbols = [stock['symbol'] for stock in stocks_collection.find({}, {'symbol': 1})]

    for symbol in stock_symbols:
        response = requests.get(ALPHA_VANTAGE_URL.format(symbol, ALPHA_VANTAGE_API_KEY))
        if response.status_code == 200:
            data = response.json().get("Global Quote", {})
            if data:
                updated_stock = {
                    "symbol": symbol,
                    "price": float(data.get("05. price", 0)),
                    "change": float(data.get("09. change", 0)),
                    "last_updated": datetime.utcnow()
                }
                stocks_collection.update_one({'symbol': symbol}, {'$set': updated_stock}, upsert=True)

    return jsonify({'message': 'Stock prices updated successfully'})

# Buy Stock Route
@app.route('/buy-stock', methods=['POST'])
def buy_stock():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    
    user_id = session['user_id']
    symbol = request.form['symbol']
    quantity = int(request.form['quantity'])
    price = float(request.form['price'])
    total_cost = quantity * price

    # Update Transactions Collection
    transaction = {
        "user_id": user_id,
        "symbol": symbol,
        "type": "buy",
        "quantity": quantity,
        "price": price,
        "total_cost": total_cost,
        "timestamp": datetime.now()
    }
    transactions_collection.insert_one(transaction)

    # Update Portfolio Collection
    portfolio = portfolios_collection.find_one({"user_id": user_id})
    if portfolio:
        found = False
        for stock in portfolio["stocks"]:
            if stock["symbol"] == symbol:
                stock["quantity"] += quantity
                stock["average_price"] = ((stock["average_price"] * (stock["quantity"] - quantity)) + total_cost) / stock["quantity"]
                found = True
                break
        if not found:
            portfolio["stocks"].append({"symbol": symbol, "quantity": quantity, "average_price": price})
        
        portfolio["total_value"] += total_cost
        portfolios_collection.update_one({"user_id": user_id}, {"$set": portfolio})
    else:
        new_portfolio = {
            "user_id": user_id,
            "stocks": [{"symbol": symbol, "quantity": quantity, "average_price": price}],
            "total_value": total_cost
        }
        portfolios_collection.insert_one(new_portfolio)

    return jsonify({'message': 'Stock purchased successfully'})

# View Portfolio Route
@app.route('/view-portfolio')
def view_portfolio():
    if 'user_id' not in session:
        flash("Please log in first!", "danger")
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    portfolio = portfolios_collection.find_one({"user_id": user_id}) or {"stocks": []}
    
    return render_template('portfolio.html', portfolio=portfolio)

@app.route('/sell_stock', methods=['POST'])
def sell_stock():
    if 'user_id' not in session:
        flash("Please log in first!", "danger")
        return redirect(url_for('login'))

    user_id = session['user_id']
    symbol = request.form['symbol']
    quantity = int(request.form['quantity'])
    average_price = float(request.form['average_price'])

    portfolio = portfolios_collection.find_one({"user_id": user_id})

    if not portfolio or not portfolio.get('stocks'):
        flash("You have no stocks to sell.", "danger")
        return redirect(url_for('view_portfolio'))

    # Remove stock from portfolio
    updated_stocks = [stock for stock in portfolio['stocks'] if stock['symbol'] != symbol]

    if not updated_stocks:
        portfolios_collection.delete_one({"user_id": user_id})
    else:
        portfolios_collection.update_one({"user_id": user_id}, {"$set": {"stocks": updated_stocks}})

    # Add transaction entry
    sell_transaction = {
        "user_id": user_id,
        "symbol": symbol,
        "type": "sell",
        "quantity": quantity,
        "price": average_price,
        "total_cost": quantity * average_price,
        "timestamp": datetime.now().isoformat()
    }
    transactions_collection.insert_one(sell_transaction)

    flash("Stock sold successfully!", "success")
    return redirect(url_for('view_portfolio'))
# View Transactions Route
@app.route('/view-transactions')
def view_transactions():
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))

    user_id = session['user_id']
    transactions = list(db.transactions.find({"user_id": user_id}))

    return render_template("view_transactions.html", transactions=transactions)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    PORT = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=PORT, debug=True)
