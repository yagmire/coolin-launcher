from flask import Flask, request, send_file, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import os, hashlib
app = Flask(__name__)
"""
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["20 per day", "6 per hour"],
    storage_uri="memory://",
)
"""


def get_beta_key():
    # Define the URL and parameters
    hasher = hashlib.sha512()
    if os.path.isfile("dingo\\betakey"):
        with open('dingo\\betakey', 'rb') as file:
            while True:
                chunk = file.read(4096)  # Read file in chunks
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    else:
        return "0"

BASE_DIRECTORY = "C:\\Users\\matthewkelley\\Desktop\\coolin-launcher\\dingo"
BETA_KEY = get_beta_key()
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
        
@app.route('/upload')
def upload():
    return 'Upload test'
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2665)
