from flask import Flask, request, send_file, abort
import os

app = Flask(__name__)

BASE_DIRECTORY = "C:\\Users\\matthewkelley\\Desktop\\coolin-launcher\\dingo"

@app.route('/download')
def download_file():
    game = request.args.get('game')
    version = request.args.get('version')
    
    if not game or not version:
        return abort(400, "Missing 'game' or 'version' parameter")

    file_path = os.path.join(BASE_DIRECTORY, game, version, f"{game}.zip")
    print(file_path)
   
    if not os.path.isfile(file_path):
        return abort(404, "File not found")

    return send_file(file_path, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2665)