from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session, abort
from flask_wtf.csrf import CSRFProtect, CSRFError
import json
import uuid
from werkzeug.utils import secure_filename
from DocumentProcessor import DocumentProcessor

app = Flask(__name__)
app.secret_key = "noone_can_guess_my_key"  # Replace with a secure key
csrf = CSRFProtect(app)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return abort(400, description="CSRF validation failed.")

# Allowed image extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# S3 Bucket Configuration
DEFAULT_BUCKET_NAME = "receipt-image-uploads"

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    items = session.get('items', {})
    people = session.get('people', [])
    colors = session.get('colors', [])
    fees = session.get('fees', {})
    totals = session.get('totals', {})

    # Calculate subtotals per person
    person_totals = {person: 0 for person in people}
    for item_id in items.keys():
        assigned_people = items[item_id]['assignments']
        if len(assigned_people) > 0:
            split_price = items[item_id]['price'] / len(assigned_people)
            for person in assigned_people:
                person_totals[person] += split_price

    return render_template('index.html',
                           items=items, people=people,
                           person_colors=colors,
                           person_totals=person_totals,
                           fees=fees,
                           totals=totals,
                           )

@app.route('/add_item', methods=['POST'])
def add_item():
    items = session.get('items', {})
    item_name = request.form.get('item_name')
    try:
        item_price = float(request.form.get('item_price'))
    except ValueError:
        flash("Invalid price. Please enter a numeric value.")
        return redirect(url_for('index'))

    item = {
        'name': item_name,
        'price': item_price,
        'assignments': []
    }

    unique_id = str(uuid.uuid4())
    items[unique_id] = item
    session['items'] = items
    flash(f"Added item: {item_name}, Price: {item_price:.2f}")
    return redirect(url_for('index'))

@app.route('/add_fee', methods=['POST'])
def add_fee():
    fees = session.get('fees', {})
    fee_name = request.form.get('fee_name')
    try:
        fee_price = float(request.form.get('fee_price'))
    except ValueError:
        flash("Invalid price. Please enter a numeric value.")
        return redirect(url_for('index'))

    fee_even_bool = request.form.get('even_split_boolean')

    fees[fee_name] = {
        "price": fee_price,
        "even_split": fee_even_bool
    }
    session['fees'] = fees
    return redirect(url_for('index'))

def generate_colors(people):
    hues = [i * 30 for i in range(12)]  # 12 hues, each 30 degrees apart (0, 30, 60, ..., 330)
    saturations = [0.45, 0.55, 0.65, 0.75]

    person_colors = {}
    saturation_index = 0

    for i, person in enumerate(people):
        hue = hues[i % len(hues)]
        saturation = saturations[saturation_index % len(saturations)]
        person_colors[person] = f"hsl({hue}, {int(saturation * 100)}%, 60%)"
        saturation_index += 1

    return person_colors

@app.route('/add_person', methods=['POST'])
def add_person():
    people = session.get('people', [])
    colors = session.get('colors', {})

    person_name = request.form.get('person_name')
    people.append(person_name)

    colors = generate_colors(people)

    session['people'] = people
    session['colors'] = colors
    return redirect(url_for('index'))

@app.route('/update_assignment', methods=['POST'])
def update_assignment():
    data = request.json  # Expecting {'item_id': 'item_id', 'person': 'person_name', 'assigned': True/False}
    items = session.get('items', {})

    # Ensure the item exists in the assignments dictionary
    item_id = data.get('item_id')
    person = data.get('person')
    assigned = data.get('assigned')

    print(data)
    
    # Update the assignment status
    if assigned:
        items[item_id]['assignments'].append(person)
    else:
        items[item_id]['assignments'].remove(person)

    session['items'] = items  # Save back to session

    return jsonify(success=True)

@app.route('/update_item', methods=['POST'])
def update_item():
    data = request.json
    item_id = data.get('item_id')
    new_name = data.get('new_name')
    new_price = float(data.get('new_price', 0))

    items = session.get('items', {})

    # Update item name and price
    items[item_id]['name'] = new_name
    items[item_id]['price'] = new_price

    session['items'] = items

    return jsonify({'success': True})

@app.route('/remove_item', methods=['POST'])
def remove_item():
    data = request.json
    item_to_remove = data.get('item_id')

    items = session.get('items', {})

    # Remove the item
    del items[item_to_remove]
    session['items'] = items

    return jsonify({'success': True})

@app.route('/update_fee', methods=['POST'])
def update_fee():
    data = request.json
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    new_price = float(data.get('new_price', 0))
    new_bool = data.get('new_bool')

    fees = session.get('fees', {})

    del fees[old_name]
    fees[new_name] = {
        "price": new_price,
        "even_split": new_bool
    }

    session['fees'] = fees

    return jsonify({'success': True})

@app.route('/remove_fee', methods=['POST'])
def remove_fee():
    data = request.json
    fee_to_remove = data.get('fee')

    fees = session.get('fees', [])

    del fees[fee_to_remove]

    session['fees'] = fees

    return jsonify({'success': True})

@app.route('/calculate_fees', methods=['POST'])
def calculate_fees():
    items = session.get('items', [])
    people = session.get('people', [])
    fees = session.get('fees', {})

    subtotals = {person: 0 for person in people}

    for item_id in items.keys():
        for person in items[item_id]['assignments']:
            subtotals[person] += items[item_id]['price']/len(items[item_id]['assignments'])

    totals = subtotals.copy()

    for feeName, feeData in fees.items():
        if feeData["even_split"]:
            for person in people:
                totals[person] += feeData["price"]/len(people)
        else:
            for person in people:
                totals[person] += feeData["price"] * subtotals[person]/sum(subtotals.values())

    session['totals'] = totals

    return redirect(url_for('index'))

@app.route('/scan_receipt')
def scan_receipt():
    tables = session.get('tables', [])
    image_urls = session.get('image_urls', [])
    return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

@app.route('/upload_receipt', methods=['POST'])
def upload_receipt():
    image_urls = session.get('image_urls', [])
    tables = session.get('tables', [])
    if 'receipt_image' not in request.files:
        flash('No file part')
        return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

    file = request.files['receipt_image']
    if file.filename == '' or not allowed_file(file.filename):
        flash('No selected file or invalid file type')
        return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

    try:
        # Upload directly to S3
        s3_key = secure_filename(file.filename)
        processor = DocumentProcessor(file_name=s3_key)
        new_url = processor.generate_presigned_url()
        if new_url == None:
            flash(f"Error generating image link")
            return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

        if not new_url in image_urls:
            image_urls.append(new_url)
            session["image_urls"] = image_urls

        processor.upload_to_s3(file)

        if not processor.textract_process():
            flash(f"Error scanning")
            return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

        processor.extract_and_fix_tables()
        tables.extend(processor.tables)
        session['tables'] = tables

        flash(f"File uploaded successfully to S3: {s3_key}")
    except Exception as e:
        flash(f"Error uploading file to S3: {str(e)}")
        return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

    return render_template('scan_receipt.html',
                           tables=tables,
                           image_urls=image_urls
                           )

@app.route('/get_items_from_scan', methods=['POST'])
def get_items_from_scan():
    try:
        # Retrieve table data from the form
        tables_json = request.form.get('tables_data')  # Assuming table data is passed as JSON strings
        items = session.get('items', {})
        tables = json.loads(tables_json)  # Parse the JSON string into a list

        for table in tables:
            for row in table:
                # Ensure each row has valid name and price
                if len(row) == 2 and row[0].strip():
                    try:
                        name = row[0].strip()
                        price = float(row[1])
                        unique_id = str(uuid.uuid4())
                        items[unique_id] = {
                            'name': name,
                            'price': price,
                            'assignments': []
                        }
                    except ValueError:
                        flash(f"Invalid price for item '{row[0]}'. Skipping.")

        # Save the items to the session
        session['items'] = items
        flash("Items saved successfully.")

        # Clear the scanned tables and image URLs from the session
        session.pop('tables', None)
        session.pop('image_urls', None)
    except Exception as e:
        flash(f"Error processing tables: {e}")

    return redirect(url_for('index'))

@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.clear()  # Clears all session data
    flash("Session data has been cleared.")
    return redirect(url_for('index'))

@app.route('/delete_image', methods=['DELETE'])
def delete_image():
    data = request.json
    image_url_to_delete = data.get('image_url')

    image_urls = session.get('image_urls', [])

    # Remove the image URL from the session
    if image_url_to_delete in image_urls:
        image_urls.remove(image_url_to_delete)
        session['image_urls'] = image_urls
        flash(f"Image {image_url_to_delete} deleted successfully.")
        return jsonify({"message": "Image deleted successfully."}), 200
    else:
        flash(f"Image {image_url_to_delete} not found.")
        return jsonify({"message": "Image not found."}), 404

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)