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
    "dingo": "dingo123dango"
}

DINGO_VERSION_CONTROL = '/dingo/dingo.json'
UPLOAD_FOLDER = '/dingo/'

def get_biggest_number_folder(path):
    folders = [f for f in os.listdir(path) if os.path.isdir(os.path.join(path, f))]
    folders = [f for f in folders if f.isdigit()]
    if not folders:
        return None
    return max(folders, key=int)


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
    if os.path.isfile("/dingo/betakey"):
        with open('/dingo/betakey', 'rb') as file:
            while True:
                chunk = file.read(4096)  # Read file in chunks
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    else:
        return "0"

BASE_DIRECTORY = "/dingo"
BETA_KEY = get_beta_key()
print(BETA_KEY, file=sys.stdout)
BETA_KEY_FILE = "/dingo/betakey"

@app.route('/get_latest_ver')
def get_latest_ver():
    game = request.args.get('game')
    branch = request.args.get('branch')
    print(game, branch, file=sys.stdout)
    if not game:
        return abort(400, "Missing 'game' parameter")
    if game not in os.listdir(BASE_DIRECTORY):
        return abort(404, "Game not found")
    if branch not in os.listdir(os.path.join(BASE_DIRECTORY, game)):
        if branch == "beta" and os.path.exists(os.path.join(BASE_DIRECTORY, game, "beta")) == False:
            branch = "stable"
            pass
        else:
            return abort(404, "Branch not found")
    version = get_biggest_number_folder(os.path.join(BASE_DIRECTORY, game, branch))
    return version

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

    folder_version = get_biggest_number_folder(os.path.join(BASE_DIRECTORY, game, version))
    
    file_path = os.path.join(BASE_DIRECTORY, game, version, folder_version,f"{game}.zip")
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

    # Check if 'stable' and 'beta' keys exist
    if 'stable' not in data or 'beta' not in data:
        print("'stable' or 'beta' key not found in data")
        return jsonify(success=False, error="'stable' or 'beta' key not found in data"), 500

    # Handle POST request to update beta key file
    if request.method == 'POST' and 'betakey' in request.form:
        new_beta_key = request.form.get('betakey')
        if not new_beta_key:
            print("Error: Beta key field is empty.")
            return jsonify(success=False, error="Beta key field cannot be empty."), 400

        try:
            # Overwrite the beta key file
            with open(BETA_KEY_FILE, 'w') as f:  # Replace BETA_KEY_FILE with the actual beta key file path
                f.write(new_beta_key)
            print("Beta key updated successfully.")
        except Exception as e:
            print(f"Error writing beta key: {e}")
            return jsonify(success=False, error="Error updating beta key."), 500

        return jsonify(success=True, message="Beta key updated successfully.")

    # Handle POST request to upload files or increment keys
    elif request.method == 'POST':
        print("Form data:", request.form)
        print("Files data:", request.files)

        # Ensure the file is in the request.files
        file = request.files.get('file')
        if file:
            print("File received:", file.filename)

            # Validate the file type
            if not file.filename.endswith('.zip'):
                print("Error: File is not a ZIP file.")
                return jsonify(success=False, error="Only ZIP files are allowed."), 400

            selected_branch = request.form.get('branch', 'stable')
            selected_key = request.form.get('key')

            if not selected_key:
                print("Error: No key selected for file upload.")
                return jsonify(success=False, error="No key selected for file upload."), 400

            # Increment the key value in the selected branch
            if selected_key in data[selected_branch]:
                data[selected_branch][selected_key] += 1
            else:
                data[selected_branch][selected_key] = 1

            # Save the updated JSON data
            with open(DINGO_VERSION_CONTROL, 'w') as f:
                json.dump(data, f, indent=4)

            key_number = data[selected_branch][selected_key]
            folder_path = os.path.join(UPLOAD_FOLDER, f"{selected_key}/{selected_branch}/{key_number}")
            os.makedirs(folder_path, exist_ok=True)

            filename = secure_filename(file.filename).lower()
            file_path = os.path.join(folder_path, filename)
            try:
                file.save(file_path)
                print(f"File {filename} saved successfully.")
            except Exception as e:
                print(f"Error saving file: {e}")
                return jsonify(success=False, error="Error saving file."), 500

    # Render HTML page with current data and file upload form
    html_template = """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin Panel</title>
        <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #121212; color: #e0e0e0; }
            .container { margin-top: 50px; }
            h1, h2, h3 { color: #ffffff; }
            .form-group label { color: #e0e0e0; }
            .form-control, .btn, .list-group-item {
                background-color: #333333; color: #e0e0e0; border: 1px solid #444444;
            }
            .btn-primary { background-color: #007bff; border-color: #007bff; }
            .btn-primary:hover { background-color: #0056b3; border-color: #0056b3; }
            .list-group-item { border-color: #444444; }
            .form-control:focus { border-color: #007bff; background-color: #2c2c2c; color: #e0e0e0; }
            .container div {
                background-color: #2a2a2a; /* Lighter background for the sections */
                border: 1px solid #444444; /* Border to distinguish the sections */
                border-radius: 10px; /* Rounded corners */
                padding: 20px; /* Padding inside the divs for better readability */
                margin-bottom: 30px; /* Space between the divs */
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="text-center">Admin Panel</h1>
            <div>
                <!-- Combined form for key increment and file upload -->
                <form method="post" action="/admin" class="mb-4" enctype="multipart/form-data">
                    <div class="form-group">
                        <label for="branch">Select Branch:</label><br>
                        <input type="radio" name="branch" value="stable" id="stable" checked> Stable<br>
                        <input type="radio" name="branch" value="beta" id="beta"> Beta
                    </div>

                    <div class="form-group">
                        <label for="key">Select Key:</label>
                        <select name="key" id="key" class="form-control">
                            <option value="">-- Select Key --</option>
                            {% for key in keys %}
                                <option value="{{ key }}">{{ key }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <h2>Upload File</h2>
                    <div class="form-group">
                        <label for="file">Choose File:</label>
                        <input type="file" name="file" id="file" class="form-control" required>
                    </div>

                    <button type="submit" class="btn btn-primary">Submit</button>
                </form>

                <h2>Current Values:</h2>
                <h3>Stable Branch:</h3>
                <ul class="list-group">
                    {% for key, value in data['stable'].items() %}
                        <li class="list-group-item"><strong>{{ key }}:</strong> {{ value }}</li>
                    {% endfor %}
                </ul>
                <h3>Beta Branch:</h3>
                <ul class="list-group">
                    {% for key, value in data['beta'].items() %}
                        <li class="list-group-item"><strong>{{ key }}:</strong> {{ value }}</li>
                    {% endfor %}
                </ul>
            </div>
            <div>
                <!-- Form to update beta key -->
                <form method="post" action="/admin" class="mb-4">
                    <h2>Update Beta Key</h2>
                    <div class="form-group">
                        <label for="betakey">Current Beta Key:</label>
                        <input type="text" name="betakey" id="betakey" class="form-control" value="{{ current_betakey }}" required>
                    </div>
                    <button type="submit" class="btn btn-danger" onclick="return confirm('Are you sure you want to update the beta key? This will kick everyone out of the beta.')">Update Beta Key</button>
                </form>
            </div>
        </div>
        <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.1/dist/umd/popper.min.js"></script>
        <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
    </body>
    </html>
    """
    # Get the current beta key from the file
    try:
        with open(BETA_KEY_FILE, 'r') as f:  # Replace BETA_KEY_FILE with the actual beta key file path
            current_betakey = f.read().strip()
    except Exception as e:
        print(f"Error reading beta key file: {e}")
        current_betakey = "Error loading beta key."

    return render_template_string(html_template, keys=data['stable'].keys(), data=data, current_betakey=current_betakey)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2665)
