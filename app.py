from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime
import os

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///finance.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    incomes = db.relationship("Income", backref="user", cascade="all, delete-orphan")
    expenses = db.relationship("Expense", backref="user", cascade="all, delete-orphan")


class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    source = db.Column(db.String(100), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200), default="")
    date = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def financial_data():
    incomes = Income.query.filter_by(user_id=current_user.id).order_by(Income.date.desc()).all()
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    total_income = sum(x.amount for x in incomes)
    total_expenses = sum(x.amount for x in expenses)
    balance = total_income - total_expenses
    categories = {}
    for expense in expenses:
        categories[expense.category] = categories.get(expense.category, 0) + expense.amount
    savings_rate = (balance / total_income * 100) if total_income else 0
    return incomes, expenses, total_income, total_expenses, balance, categories, savings_rate


def local_advice():
    _, _, income, expenses, balance, categories, savings = financial_data()
    tips = []

    if income == 0:
        tips.append("Add your income first so the advisor can build a personalized budget.")
    else:
        tips.append(f"You recorded ₹{income:,.2f} of income and ₹{expenses:,.2f} of expenses.")
        if balance < 0:
            tips.append("Your recorded expenses are above income. Review the largest categories first.")
        elif savings < 20:
            tips.append("Your current recorded savings rate is below 20%. Consider reducing non-essential spending.")
        else:
            tips.append("You are recording positive savings. Keep monitoring your largest spending categories.")

    if categories:
        top = max(categories, key=categories.get)
        tips.append(f"Your largest recorded expense category is {top} at ₹{categories[top]:,.2f}.")

    tips.extend([
        "Track expenses consistently to make the monthly picture more accurate.",
        "Use the EMI calculator before taking on a new loan.",
        "Set a realistic savings goal and review progress each month."
    ])
    return tips


def ask_gemini(question):
    _, _, income, expenses, balance, categories, savings = financial_data()

    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        context = (
            f"User financial snapshot: income ₹{income:,.2f}; "
            f"expenses ₹{expenses:,.2f}; balance ₹{balance:,.2f}; "
            f"savings rate {savings:.1f}%; categories {categories}."
        )

        prompt = f"""You are a friendly personal finance education assistant inside a Flask student project.
Give practical, general financial education based only on the provided snapshot.
Do not request sensitive credentials. Do not claim to be a financial adviser.
Keep the answer concise, clear, and actionable.

{context}

User question: {question}
"""

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        return response.text

    except Exception as exc:
        print("Gemini error:", exc)
        return None


@app.route("/")
def home():
    return redirect(url_for("dashboard" if current_user.is_authenticated else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            return render_template("register.html", error="Please fill in all fields.")

        if len(password) < 6:
            return render_template("register.html", error="Password must contain at least 6 characters.")

        if User.query.filter_by(username=username).first():
            return render_template("register.html", error="Username already exists.")

        if User.query.filter_by(email=email).first():
            return render_template("register.html", error="Email is already registered.")

        db.session.add(User(
            username=username,
            email=email,
            password=generate_password_hash(password)
        ))
        db.session.commit()

        flash("Account created. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        user = User.query.filter_by(
            username=request.form.get("username", "").strip()
        ).first()

        if user and check_password_hash(
            user.password,
            request.form.get("password", "")
        ):
            login_user(user)
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    incomes, expenses, total_income, total_expenses, balance, categories, savings_rate = financial_data()

    health = 40 if balance < 0 else min(95, max(60, int(60 + savings_rate)))

    return render_template(
        "dashboard.html",
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        categories=categories,
        savings_rate=savings_rate,
        financial_health=health,
        recent_expenses=expenses[:5],
        recent_incomes=incomes[:5]
    )


@app.route("/add_income", methods=["POST"])
@login_required
def add_income():
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0

    if amount <= 0:
        flash("Enter a valid income amount.")
    else:
        db.session.add(Income(
            user_id=current_user.id,
            amount=amount,
            source=request.form.get("source", "Other").strip() or "Other"
        ))
        db.session.commit()
        flash("Income added.")

    return redirect(url_for("dashboard"))


@app.route("/add_expense", methods=["POST"])
@login_required
def add_expense():
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0

    if amount <= 0:
        flash("Enter a valid expense amount.")
    else:
        db.session.add(Expense(
            user_id=current_user.id,
            amount=amount,
            category=request.form.get("category", "Other"),
            description=request.form.get("description", "").strip()
        ))
        db.session.commit()
        flash("Expense added.")

    return redirect(url_for("dashboard"))


@app.route("/delete_expense/<int:item_id>", methods=["POST"])
@login_required
def delete_expense(item_id):
    item = db.session.get(Expense, item_id)

    if item and item.user_id == current_user.id:
        db.session.delete(item)
        db.session.commit()

    return redirect(url_for("dashboard"))


@app.route("/delete_income/<int:item_id>", methods=["POST"])
@login_required
def delete_income(item_id):
    item = db.session.get(Income, item_id)

    if item and item.user_id == current_user.id:
        db.session.delete(item)
        db.session.commit()

    return redirect(url_for("dashboard"))


@app.route("/financial-summary")
@login_required
def financial_summary():
    _, _, income, expenses, balance, categories, savings = financial_data()

    return render_template(
        "summary.html",
        total_income=income,
        total_expenses=expenses,
        balance=balance,
        categories=categories,
        savings_rate=savings
    )


@app.route("/financial-tips")
@login_required
def financial_tips():
    return render_template("tips.html", tips=local_advice())


@app.route("/ai-advisor", methods=["GET", "POST"])
@login_required
def ai_advisor():
    answer = None
    question = ""

    if request.method == "POST":
        question = request.form.get("question", "").strip()

        if question:
            answer = ask_gemini(question)

            if answer is None:
                answer = (
                    "Gemini is not available right now. "
                    "Here are recommendations based on your recorded data:\n\n"
                    + "\n".join("• " + x for x in local_advice())
                )

    return render_template(
        "ai.html",
        answer=answer,
        question=question,
        gemini_ready=bool(GEMINI_API_KEY and GEMINI_AVAILABLE)
    )


@app.route("/api/ask", methods=["POST"])
@login_required
def api_ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()

    if not question:
        return jsonify({
            "success": False,
            "message": "Please enter a question."
        }), 400

    answer = ask_gemini(question)

    if answer is None:
        answer = "\n".join("• " + x for x in local_advice())

    return jsonify({
        "success": True,
        "answer": answer
    })


@app.route("/credit-analyzer")
@login_required
def credit_analyzer():
    return render_template("credit.html", score=742)


def calculator(title):
    result = None

    if request.method == "POST":
        try:
            amount = float(request.form.get("amount", 0))
            rate = float(request.form.get("rate", 0))

            if title == "Loan Calculator":
                months = int(request.form.get("years", 0)) * 12
            else:
                months = int(request.form.get("months", 0))

            if amount <= 0 or months <= 0:
                raise ValueError

            monthly_rate = rate / 100 / 12

            if monthly_rate == 0:
                emi = amount / months
            else:
                emi = (
                    amount * monthly_rate * (1 + monthly_rate) ** months
                    / ((1 + monthly_rate) ** months - 1)
                )

            result = {
                "emi": emi,
                "interest": emi * months - amount,
                "total": emi * months
            }

        except (ValueError, ZeroDivisionError):
            flash("Enter valid calculator values.")

    return render_template(
        "calculator.html",
        calculator_type=title,
        result=result
    )


@app.route("/loan-calculator", methods=["GET", "POST"])
@login_required
def loan_calculator():
    return calculator("Loan Calculator")


@app.route("/emi-calculator", methods=["GET", "POST"])
@login_required
def emi_calculator():
    return calculator("EMI Calculator")


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
