import base64
import io
import os
import zlib
from tkinter.tix import Form

import bcrypt
import data as data
from flask import Flask, request, render_template, redirect, url_for, jsonify, session, current_app, flash
from flask_sqlalchemy import SQLAlchemy
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from pip._internal.utils import datetime
from sqlalchemy import text
from base64 import b64encode
import requests
from datetime import datetime

from sqlalchemy.testing.pickleable import User
from werkzeug.security import check_password_hash

app = Flask(__name__)

# Your Telegram Bot API token
TELEGRAM_BOT_TOKEN = '7043304977:AAH1liq3drA51XyuzQIVlGbpy0Pd3PmpSaU'
# Your Telegram channel chat ID (e.g., @your_channel_name or a numeric chat ID)
TELEGRAM_CHAT_ID = '@ST34_Notify_Channel'

# MySQL Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:root@localhost/pos'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'supersecretkey'  # Secret key for session management
db = SQLAlchemy(app)


@app.template_filter('b64encode')
def b64encode_filter(data):
    if data is None:
        return ''
    return base64.b64encode(data).decode('utf-8')


# Route for the Login Page
@app.route('/login', methods=['GET', 'POST'])
def poslogin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Query the database for the user without using an ORM model
        user = db.session.execute(text('SELECT id,username,password,email,image FROM user WHERE username = :username'), {'username': username}).fetchone()

        if user and user.password == password:
            session['id'] = user.id
            session['username'] = user.username
            session['email'] = user.email

            return redirect(url_for('pos'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('poslogin.html')


# Route for the Registration Page
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # Handle the image upload
        if 'profile_image' in request.files:
            profile_image = request.files['profile_image']
            if profile_image:
                image_data = profile_image.read()  # Read image data
            else:
                image_data = None
        else:
            image_data = None

        # Insert the new user into the database
        db.session.execute(
            text('INSERT INTO user (username, email, password, image) VALUES (:username, :email, :password, :image)'),
            {
                'username': username,
                'email': email,
                'password': password,
                'image': image_data
            }
        )
        db.session.commit()

        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('poslogin'))

    return render_template('register.html')


@app.route('/get_user', methods=['GET'])
def get_user():
    # Assuming you pass the user_id as a query parameter, e.g., /get_user?user_id=1
    user_id = request.args.get('id')

    # SQL query to get the user by ID, wrapped in text() for SQLAlchemy
    query = text('''
    SELECT id, username, email, password, image
    FROM user
    WHERE id = :user_id
    ''')

    # Execute the query with the user_id parameter
    user = db.session.execute(query, {'user_id': user_id}).fetchone()

    if user:
        # If the user exists, return user details
        return jsonify({
            'profileImage': base64.b64encode(user.image).decode(
                'utf-8') if user.image else 'https://via.placeholder.com/50',
            'fullName': user.username
        })
    else:
        # If user doesn't exist, return an error
        return jsonify({'error': 'User not found'}), 404


# Fetch categories route
@app.route('/get_categories', methods=['GET'])
def get_categories():
    query = text('SELECT category_id, name FROM category')
    categories = db.session.execute(query).fetchall()

    category_list = [{
        'category_id': category.category_id,
        'name': category.name
    } for category in categories]

    return jsonify({'categories': category_list})


@app.route('/buy_product', methods=['POST'])
def buy_product():
    data = request.get_json()  # Get the request data
    product_id = data['product_id']
    quantity = int(data['quantity'])
    customer_name = data['customer_name']
    customer_email = data['customer_email']

    try:
        # Start a transaction
        with db.session.begin():
            # Retrieve the product details
            product_query = text("""
                SELECT * 
                FROM product 
                WHERE product_id = :product_id
            """)
            product = db.session.execute(product_query, {'product_id': product_id}).fetchone()

            if not product or product.stock < quantity:
                return jsonify({'error': 'Insufficient stock'}), 400

            total_price = product.price * quantity

            # Insert the new order
            order_query = text("""
                INSERT INTO `order` 
                (product_name, product_image, product_description, product_price, size, color, category, order_date, quantity, total_price, order_status, customer_name, customer_email)
                VALUES
                (:product_name, :product_image, :product_description, :product_price, :size, :color, :category, :order_date, :quantity, :total_price, :order_status, :customer_name, :customer_email)
            """)
            db.session.execute(order_query, {
                'product_name': product.name,
                'product_image': product.product_image,
                'product_description': product.description,
                'product_price': product.price,
                'size': product.size_id,
                'color': product.color_id,
                'category': product.category_id,
                'order_date': datetime.now(),
                'quantity': quantity,
                'total_price': total_price,
                'order_status': 'Pending',  # Use a constant or enum for better clarity
                'customer_name': customer_name,
                'customer_email': customer_email
            })

            # Update the product stock
            update_stock_query = text("""
                UPDATE product
                SET stock = stock - :quantity
                WHERE product_id = :product_id
            """)
            db.session.execute(update_stock_query, {'quantity': quantity, 'product_id': product_id})

            # Transaction successful
            # Prepare the message to send to Telegram
            message = (
                f"🎉 **New Purchase Alert!** 🎉\n\n"
                f"**Customer Name:** {customer_name}\n"
                f"**Customer Email:** {customer_email}\n"
                f"**Product Name:** {product.name}\n"
                f"**Quantity:** {quantity}\n"
                f"**Total Price:** ${total_price:.2f}\n"
                f"**Order Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"📦 Thank you for shopping with us!"
            )

            # Send the message to the Telegram bot
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            response = requests.post(telegram_url, json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'  # To format the message nicely
            })

            if response.status_code != 200:
                # Log Telegram API errors if necessary
                print(f"Failed to send message to Telegram: {response.text}")

        # Transaction successful
        return jsonify({"message": "Order placed successfully"}), 200

    except Exception as e:
        db.session.rollback()  # Rollback in case of failure
        return jsonify({'error': 'Database operation failed', 'details': str(e)}), 500


@app.route('/get_products', methods=['GET'])
def get_products():
    category_id = request.args.get('category_id')  # Get the category_id from the query string

    # Modify the query to filter products by category_id if provided
    if category_id:
        query = text('''SELECT product_id, name, product_image, price, stock 
                         FROM product 
                         WHERE category_id = :category_id''')
        products = db.session.execute(query, {'category_id': category_id}).fetchall()
    else:
        query = text('''SELECT product_id, name, product_image, price, stock FROM product''')
        products = db.session.execute(query).fetchall()

    product_list = [{
        'product_id': product.product_id,
        'name': product.name,
        'product_image': base64.b64encode(product.product_image).decode('utf-8') if product.product_image else 'https://via.placeholder.com/100',
        'price': product.price,
        'stock': product.stock  # Include stock information
    } for product in products]

    return jsonify({'products': product_list})


@app.route('/pos')
def pos():
    if 'id' not in session:
        flash('Please log in to access the POS page.', 'warning')
        return redirect(url_for('poslogin'))

    # Fetch user details
    user = db.session.execute(text('SELECT * FROM user WHERE id = :id'), {'id': session['id']}).fetchone()

    if user and user.image:
        # Encode the image as Base64 and prefix with MIME type
        profile_image = f"data:image/png;base64,{base64.b64encode(user.image).decode('utf-8')}"
    else:
        # Default placeholder image
        profile_image = 'https://via.placeholder.com/50'

    return render_template('pos.html', username=user.username, email=user.email, user_profile_image=profile_image)


@app.route('/logout')
def poslogout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('poslogin'))


@app.route('/delete_order/<int:order_id>', methods=['POST'])
def delete_order(order_id):
    # Raw SQL query to delete the product (wrapped in text())
    delete_query = text("DELETE FROM `order` WHERE order_id = :order_id")
    db.session.execute(delete_query, {'order_id': order_id})

    # Commit the changes to the database
    db.session.commit()

    return redirect(url_for('reports'))


# Edit Product Route
@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    # Directly querying the product by its product_id
    product = db.session.execute(text('SELECT * FROM product WHERE product_id = :product_id'), {'product_id': product_id}).fetchone()

    if not product:
        return "Product not found", 404

    # Helper functions to get data from the respective tables
    def get_sizes():
        return db.session.execute(text('SELECT * FROM size')).fetchall()

    def get_categories():
        return db.session.execute(text('SELECT * FROM category')).fetchall()

    def get_materials():
        return db.session.execute(text('SELECT * FROM material')).fetchall()

    def get_colors():
        return db.session.execute(text('SELECT * FROM color')).fetchall()

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        stock = request.form.get('stock')
        price = request.form.get('price')
        size_id = request.form.get('size')
        category_id = request.form.get('category')
        material_id = request.form.get('material')
        color_id = request.form.get('color')

        # If a new image is uploaded, update the image
        if 'image' in request.files:
            product_image = request.files['image']
            if product_image:
                product_image_data = product_image.read()  # Save the image as binary data
            else:
                product_image_data = product.product_image  # Keep existing image if none uploaded
        else:
            product_image_data = product.product_image  # Keep existing image if no file provided

        # Update the product in the database
        db.session.execute(text(''' 
            UPDATE product SET 
                name = :name,
                description = :description,
                stock = :stock,
                price = :price,
                size_id = :size_id,
                category_id = :category_id,
                material_id = :material_id,
                color_id = :color_id,
                product_image = :product_image
            WHERE product_id = :product_id
        '''), {
            'name': name,
            'description': description,
            'stock': stock,
            'price': price,
            'size_id': size_id,
            'category_id': category_id,
            'material_id': material_id,
            'color_id': color_id,
            'product_image': product_image_data,
            'product_id': product_id
        })
        db.session.commit()

        return redirect(url_for('product', product_id=product_id))  # Redirect to the same page to reload with updated data

    # If the request is GET, pre-fill the form with the existing product details
    sizes = get_sizes()  # Get all sizes from the size table
    categories = get_categories()  # Get all categories from the category table
    materials = get_materials()  # Get all materials from the material table
    colors = get_colors()  # Get all colors from the color table

    return render_template('edit_product.html',
                           product=product,
                           sizes=sizes,
                           categories=categories,
                           materials=materials,
                           colors=colors)


@app.route("/edit_user/<int:user_id>", methods=["GET", "POST"])
def edit_user(user_id):
    # Query to fetch the user by their ID using raw SQL
    result = db.session.execute(
        text("SELECT id, username, email, image FROM user WHERE id = :id"), {"id": user_id}
    ).fetchone()

    if result is None:
        # If user not found, redirect to user list or return a 404 page
        return redirect(url_for("user_list"))

    # Get user data from result
    username = result.username
    email = result.email
    image = result.image

    if request.method == "POST":
        # Get form data
        new_username = request.form.get("username")
        new_email = request.form.get("email")
        new_password = request.form.get("password")  # Remember to hash the password before saving

        # If there is a new image file
        if "image" in request.files:
            image_file = request.files["image"]
            if image_file:
                image = image_file.read()  # Read image data

        # Update the user data in the database with a SQL query
        db.session.execute(
            text("UPDATE user SET username = :username, email = :email, password = :password, image = :image WHERE id = :id"),
            {
                "username": new_username,
                "email": new_email,
                "password": new_password,  # Hash password if necessary
                "image": image,
                "id": user_id
            }
        )

        db.session.commit()

        # Redirect to the user list or a success page
        return redirect(url_for("user"))

    # Return the edit page with the current user data
    return render_template("edit_user.html", user=result)


@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    # Raw SQL query to delete the product (wrapped in text())
    delete_query = text("DELETE FROM product WHERE product_id = :product_id")
    db.session.execute(delete_query, {'product_id': product_id})  # Executes the query using db.session

    # Commit the changes to the database
    db.session.commit()

    return redirect(url_for('product'))


@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):
    try:
        # Delete related records
        delete_email_query = text("DELETE FROM email WHERE user_id = :id")
        db.session.execute(delete_email_query, {'id': id})

        # Delete the user record
        delete_user_query = text("DELETE FROM user WHERE id = :id")
        db.session.execute(delete_user_query, {'id': id})

        # Commit changes
        db.session.commit()
        return redirect(url_for('user'))
    except Exception as e:
        print(f"Error: {e}")
        return redirect(url_for('user', error_message="Failed to delete user."))


@app.route("/dashboard")
def dashboard():
    if 'admin_logged_in' in session:
        total_price = db.session.execute(text("SELECT SUM(total_price) AS total_order_price FROM pos.order;")).fetchone()[0]
        total_orders = db.session.execute(
            text("SELECT COUNT(*) AS total_rows FROM pos.order;")).fetchone()[0]
        total_users = db.session.execute(
            text("SELECT COUNT(*) AS total_users FROM pos.user;")).fetchone()[0]
        total_products = db.session.execute(
            text("SELECT COUNT(*) AS total_products FROM pos.product;")).fetchone()[0]
        return render_template('admin.html', total_price=total_price, total_orders=total_orders,
                               total_users=total_users, total_products=total_products)
    else:
        flash('Please log in to access the dashboard.', 'warning')
        return redirect(url_for('login'))  # Ensure correct route


# Logout route


# Logout Route
@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# Decorator to Protect Routes
def login_required(func):
    def wrapper(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Access restricted. Please log in.', 'warning')
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


@app.route("/",methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        admin = db.session.execute(text("""
               SELECT * FROM admin WHERE username = :username
           """), {'username': username}).fetchone()

        if admin and admin.password == password:
            # Store the plain text password (for migration purposes)
            db.session.execute(text("""
                   UPDATE admin SET password = :password WHERE id = :id
               """), {'password': password, 'id': admin.id})
            db.session.commit()

            session['admin_logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials.', 'danger')

    return render_template('login.html')


@app.route("/addcoupon", methods=['GET','POST'])
def coupon():
    if request.method == 'POST':
        # Retrieve form data
        coupon_id = request.form['coupon']
        coupon_amount = request.form['coupon_amount']
        user_id = request.form['user']

        # Insert product into the database using raw SQL with `text()`
        try:
            # Construct the SQL query to insert the product data
            insert_query = text("""
                UPDATE year4ecommerce.user
                SET coupon_id = :coupon_id,
                    coupon_amount = :coupon_amount
                WHERE id = :user_id;

               """)

            # Execute the query with parameters
            db.session.execute(insert_query, {
                'coupon_id': coupon_id,
                'coupon_amount': coupon_amount,
                'user_id': user_id
            })

            # Commit the transaction
            db.session.commit()

            # Redirect after successful insertion
            return redirect(url_for('coupon'))

        except Exception as e:
            error_message = str(e)
            print(f"Error: {error_message}")  # Debugging line
            return render_template('addcoupon.html', error_message=error_message)

        # Fetch users
    users = db.session.execute(text("SELECT * FROM user")).fetchall()
    return render_template("addcoupon.html", users=users)


@app.route("/adduser", methods=['GET', 'POST'])
def user():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Retrieve form data
        image_file = request.files['image']
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']

        # Read image binary data
        image_data = image_file.read()

        try:
            # Insert user into the database
            insert_query = text("""
                INSERT INTO user (username, password, email, image)
                VALUES (:username, :password, :email, :image)
            """)
            db.session.execute(insert_query, {
                'username': username,
                'password': password,
                'email': email,
                'image': image_data,
            })
            db.session.commit()
            return redirect(url_for('user'))

        except Exception as e:
            print(f"Error: {e}")
            return render_template('adduser.html', error_message=str(e))

    # Fetch users from the database
    users = db.session.execute(text("SELECT id, username, password, email, image FROM user")).fetchall()

    # Convert user data to a mutable structure and encode image in Base64
    users_list = []
    for user in users:
        user_data = {
            'id': user.id,
            'username': user.username,
            'password': user.password,
            'email': user.email,
            'image': None
        }
        if user.image:
            user_data['image'] = base64.b64encode(user.image).decode('utf-8')  # Encode image to Base64
        users_list.append(user_data)

    return render_template("adduser.html", users=users_list)


@app.route("/sendemail", methods=['GET','POST'])
def sendemail():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Retrieve form data
        message = request.form['message']
        user = request.form['user']

        # Insert product into the database using raw SQL with `text()`
        try:
            # Construct the SQL query to insert the product data
            insert_query = text("""
            INSERT INTO email (description, user_id)
            VALUES (:message, :user)
            """)

            # Execute the query with parameters
            db.session.execute(insert_query, {
                'message': message,
                'user': user,
            })

            # Commit the transaction
            db.session.commit()

            # Redirect after successful insertion
            return redirect(url_for('sendemail'))

        except Exception as e:
            error_message = str(e)
            print(f"Error: {error_message}")  # Debugging line
            return render_template('sendemail.html', error_message=error_message)

    # Fetch users
    users = db.session.execute(text("SELECT * FROM user")).fetchall()
    return render_template("sendemail.html", users=users)


@app.route("/reports")
def reports():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    # Fetch orders for display using raw SQL queries with `text()`
    orders = db.session.execute(text("SELECT * FROM `order`")).fetchall()

    # Convert orders to a list of dictionaries and handle the image conversion
    order_list = []
    column_names = ['order_id', 'product_name', 'product_image', 'product_description', 'product_price', 'size', 'color', 'category', 'order_date', 'quantity',
                    'total_price', 'order_status', 'customer_name', 'customer_email']  # Add column names

    for order in orders:
        order_dict = {}
        for i, column in enumerate(column_names):  # Access tuple by index
            order_dict[column] = order[i]  # Corrected here
        if order_dict.get('product_image'):
            order_dict['product_image'] = base64.b64encode(order_dict['product_image']).decode('utf-8')
        order_list.append(order_dict)  # Corrected here

    return render_template("reports.html", orders=order_list)  # Pass the list of orders


@app.route('/product', methods=['GET', 'POST'])
def product():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Retrieve form data
        name = request.form['name']
        image = request.files['image']
        description = request.form['description']
        size = request.form['size']
        category = request.form['category']
        stock = request.form['stock']
        price = request.form['price']
        material = request.form['material']
        color = request.form['color']

        # Process image
        image_data = image.read()

        # Insert product into the database using raw SQL with `text()`
        try:
            # Construct the SQL query to insert the product data
            insert_query = text("""
            INSERT INTO product (name, product_image, description, size_id, category_id, stock, price, material_id, color_id)
            VALUES (:name, :image_data, :description, :size, :category, :stock, :price, :material, :color)
            """)

            # Execute the query with parameters
            db.session.execute(insert_query, {
                'name': name,
                'image_data': image_data,
                'description': description,
                'size': size,
                'category': category,
                'stock': stock,
                'price': price,
                'material': material,
                'color': color
            })

            # Commit the transaction
            db.session.commit()

            # Redirect after successful insertion
            return redirect(url_for('product'))

        except Exception as e:
            error_message = str(e)
            return render_template('product.html', error_message=error_message)

    # Fetch sizes, categories, materials, and colors using raw SQL queries with `text()`
    sizes = db.session.execute(text("SELECT size_id, description FROM size")).fetchall()
    categories = db.session.execute(text("SELECT category_id, name FROM category")).fetchall()
    materials = db.session.execute(text("SELECT material_id, name FROM material")).fetchall()
    colors = db.session.execute(text("SELECT color_id, color_name FROM color")).fetchall()

    # Fetch products for display using raw SQL queries with `text()`
    products = db.session.execute(text("SELECT * FROM product")).fetchall()

    # Convert products to a list of dictionaries and handle the image conversion
    product_list = []
    column_names = ['product_id', 'name', 'product_image', 'description', 'size_id', 'category_id', 'stock', 'price', 'material_id', 'color_id']  # Add column names
    for product in products:
        product_dict = {}
        for i, column in enumerate(column_names):  # Access tuple by index
            product_dict[column] = product[i]
        if product_dict.get('product_image'):
            product_dict['product_image'] = base64.b64encode(product_dict['product_image']).decode('utf-8')
        product_list.append(product_dict)

    return render_template('product.html', sizes=sizes, categories=categories, materials=materials, colors=colors, products=product_list)


# Helper function to fetch data
def fetch_data(query):
    data = []
    try:
        with db.session.begin():
            result = db.session.execute(text(query))
            for row in result:
                data.append(dict(zip(result.keys(), row)))
    except Exception as e:
        print(f"Error: {e}")
    return data


# Helper function to fetch data
def fetch_data(query):
    data = []
    try:
        with db.session.begin():
            result = db.session.execute(text(query))
            for row in result:
                data.append(dict(zip(result.keys(), row)))
    except Exception as e:
        print(f"Error: {e}")
    return data


if __name__ == "__main__":
    app.run(debug=True)
