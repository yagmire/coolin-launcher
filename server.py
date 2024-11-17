from flask import Flask, request, send_file, abort, jsonify, render_template_string
import json, os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_httpauth import HTTPBasicAuth
from werkzeug.utils import secure_filename

import os, hashlib, sys
app = Flask(__name__)
auth = HTTPBasicAuth()


users = {
    "admin": "password123",  # Replace with your username and password
}

DINGO_VERSION_CONTROL = 'dingo\\dingo.json'
UPLOAD_FOLDER = 'dingo\\'



"""
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["20 per day", "6 per hour"],
    storage_uri="memory://",
)
"""
@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username
    return None

def get_beta_key():
    # Define the URL and parameters
    hasher = hashlib.sha512()
    if os.path.isfile("C:\\Users\\Matthew\\Documents\\GitHub\\coolin-launcher\\dingo\\betakey"):
        with open('dingo\\betakey', 'rb') as file:
            while True:
                chunk = file.read(4096)  # Read file in chunks
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    else:
        return "0"

BASE_DIRECTORY = "C:\\Users\\Matthew\\Documents\\GitHub\\coolin-launcher\\dingo"
BETA_KEY = get_beta_key()
print(BETA_KEY, file=sys.stdout)
@app.route('/download')
def download_file():
    game = request.args.get('game')
    version = request.args.get('version')
    
    if not game or not version:
        return abort(400, "Missing 'game' or 'version' parameter")

    if game not in os.listdir(BASE_DIRECTORY):
        return abort(404, "Game not found")

    if version not in os.listdir(os.path.join(BASE_DIRECTORY, game)):
        return abort(404, "Version not found")

    file_path = os.path.join(BASE_DIRECTORY, game, version, f"{game}.zip")
    print(file_path)
   
    if not os.path.isfile(file_path):
        return abort(404, "File not found")

    return send_file(file_path, as_attachment=True)
@app.route("/betakey")
def check_beta_key_validity():
    
    if request.args.get("key") == BETA_KEY:
        return "Valid"
    else:
        return "Invalid"
        
@app.route('/admin', methods=['GET', 'POST'])
@auth.login_required  # This requires authentication to access the route
def admin():
    # Load JSON data
    with open(DINGO_VERSION_CONTROL, 'r') as f:
        try:
            data = json.load(f)
            print("Data loaded:", data)  # Debugging line
        except json.JSONDecodeError as e:
            print("Error loading JSON:", e)
            return jsonify(success=False, error="Invalid JSON format"), 500

    # Check if 'latests' key exists
    if 'latests' not in data:
        print("'latests' key not found in data")
        return jsonify(success=False, error="'latests' key not found in data"), 500

    # Handle POST request to update values and file upload
    if request.method == 'POST':
        # Debugging: Print the entire form and file data
        print("Form data:", request.form)  # Check the form data (key, etc.)
        print("Files data:", request.files)  # Check all file data

        # Ensure the file is actually in the request.files
        file = request.files.get('file')
        if file:
            print("File received:", file.filename)  # Check if file is received correctly
        else:
            print("No file found in the request.")

        if file:
            selected_key = request.form.get('key')
            if not selected_key:
                print("Error: No key selected for file upload.")
                return jsonify(success=False, error="No key selected for file upload."), 400

            key_number = data['latests'].get(selected_key, 1)
            print(f"Selected Key: {selected_key}, Key Number: {key_number}")  # Debugging

            # Ensure the directory exists, and create it if necessary
            folder_path = os.path.join(UPLOAD_FOLDER, f"{selected_key}/{key_number}")
            print(f"Folder path: {folder_path}")  # Debugging
            os.makedirs(folder_path, exist_ok=True)

            # Check if the directory exists and is accessible
            if os.path.exists(folder_path):
                print(f"Directory exists: {folder_path}")
            else:
                print(f"Error: Directory {folder_path} could not be created.")
            
            # Secure the filename and prepare the full file path
            filename = secure_filename(file.filename)
            file_path = os.path.join(folder_path, filename)
            print(f"Saving file to: {file_path}")  # Debugging line to verify the file path

            # Save the file to the constructed path
            try:
                file.save(file_path)
                print(f"File {filename} saved successfully.")
            except Exception as e:
                print(f"Error saving file: {e}")

    else:
        print("No file received.")

    # Render HTML page with current data and file upload form
    html_template = """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://dolphin-emu.org/m/static/css/bootstrap-theme.min.c1c924a4f6b3.css">
        <title>Admin Panel</title>
        <!-- Bootstrap CSS -->
        <link href="https://dolphin-emu.org/m/static/css/bootstrap.min.9e0acbc8a914.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <h1 class="text-center">Admin Panel</h1>

            <!-- Combined form for both key increase and file upload -->
            <form method="post" action="/admin" class="mb-4" enctype="multipart/form-data">
                <!-- Select Key to Increase and File Upload -->
                <div class="form-group">
                    <label for="key">Select Key:</label>
                    <select name="key" id="key" class="form-control">
                        <option value="">-- Select Key --</option>
                        {% for key in keys %}
                            <option value="{{ key }}">{{ key }}</option>
                        {% endfor %}
                    </select>
                </div>

                <!-- File Upload Section -->
                <h2>Upload File</h2>
                <div class="form-group">
                    <label for="file">Choose File:</label>
                    <input type="file" name="file" id="file" class="form-control" required>
                </div>

                <button type="submit" class="btn btn-primary">Submit</button>
            </form>

            <h2>Current Values:</h2>
            <ul class="list-group">
                {% for key, value in data['latests'].items() %}
                    <li class="list-group-item">
                        <strong>{{ key }}:</strong> {{ value }}
                    </li>
                {% endfor %}
            </ul>
        </div>

        <!-- Bootstrap JS, Popper.js, and jQuery (for functionality) -->
        <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.1/dist/umd/popper.min.js"></script>
        <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
    </body>
    </html>
    """
    return render_template_string(html_template, keys=data['latests'].keys(), data=data)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2665)
