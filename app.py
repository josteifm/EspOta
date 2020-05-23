from flask import Flask, request, send_from_directory, jsonify, Response
from werkzeug.utils import secure_filename
from datetime import datetime
import hashlib
import os
import glob
import logging

UPLOAD_FOLDER = './files/'
ALLOWED_EXTENSIONS = {'bin'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/{:%Y-%m-%d}.log".format(datetime.now())),
        logging.StreamHandler()
    ]
)

header_X_ESP8266_SKETCH_MD5 = 'X-ESP8266-SKETCH-MD5'
header_X_ESP8266_STA_MAC = 'X-ESP8266-STA-MAC'
header_X_ESP8266_AP_MAC = 'X-ESP8266-AP-MAC'
header_X_ESP8266_FREE_SPACE = 'X-ESP8266-FREE-SPACE'
header_X_ESP8266_SKETCH_SIZE = 'X-ESP8266-SKETCH-SIZE'
header_X_ESP8266_CHIP_SIZE = 'X-ESP8266-CHIP-SIZE'
header_X_ESP8266_SDK_VERSION = 'X-ESP8266-SDK-VERSION'

basepath = './files/'


def check_header(name, value=None):
    print(name + ' : ' + str(request.headers.get(name)))
    if request.headers.get(name) is None:
        return False

    if value and request.headers.get(name).lower() != value.lower():
        return False

    return True


@app.route('/')
def hello_world():
    return 'Hello, World!'


@app.route('/headers')
def headers():
    request_headers = request.headers
    str_headers = ''
    for key, value in request_headers.items():
        str_headers += key + ' ' + value + '<br>'
    return str_headers


def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


@app.route('/file')
def send_file():
    # if not check_header('User-Agent', 'ESP8266-http-Update'):
    #     resp = Response("only for ESP8266 updater!\n", status=403)
    #     return resp

    if not check_header(header_X_ESP8266_STA_MAC) or not check_header(header_X_ESP8266_AP_MAC) or not check_header(
            header_X_ESP8266_FREE_SPACE) or not check_header(header_X_ESP8266_SKETCH_SIZE) or not check_header(
            header_X_ESP8266_SKETCH_MD5) or not check_header(header_X_ESP8266_CHIP_SIZE) or not check_header(header_X_ESP8266_SDK_VERSION):
        resp = Response("only for ESP8266 updater! (header)\n", status=403)
        return resp

    esp8266_ap_mac = request.headers.get(header_X_ESP8266_AP_MAC)
    esp8266_sta_mac = request.headers.get(header_X_ESP8266_STA_MAC)
    logging.info("Request from device MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))

    file_path = basepath + esp8266_ap_mac.replace(":", "")
    if not os.path.exists(file_path):
        resp = Response("No firmware for this chip {}\n".format(esp8266_ap_mac), status=404)
        logging.info("No firmware for this chip MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))
        return resp

    files = list(filter(os.path.isfile, glob.glob(file_path + "/*")))

    print(files)
    files.sort(key=os.path.getctime)
    print(files[0])

    # get file for requesing chip
    fw_file = files[0]
    fw_md5 = md5(fw_file)

    print(fw_md5)
    fw_filename = os.path.basename(fw_file)
    print(fw_filename)

    if request.headers.get(header_X_ESP8266_SKETCH_MD5) == fw_md5:
        resp = Response("Firmware is newest version\n", status=304)
        logging.info("Firmware is newest version for this chip MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))
        return resp

    logging.info("Serving FW {} for this chip MAC AP: {} MAC STA: {}".format(fw_filename, esp8266_ap_mac, esp8266_sta_mac))
    resp = send_from_directory(file_path, fw_filename)
    resp.headers['X-MD5'] = fw_md5
    return resp


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print('No file part')
            return Response("Bad Request\n", status=400)
        file = request.files['file']
        path = request.form['deviceid']
        print("Path: {}".format(path))
        # if user does not select file, browser also
        # submit an empty part without filename
        if path == '':
            print('No path')
            resp = Response("No path\n", status=200)
            return resp

        if file.filename == '':
            print('No selected file')
            resp = Response("No selected file\n", status=200)
            return resp

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], path)

            if not os.path.exists(path):
                os.makedirs(path)

            print(os.path.join(path, filename))
            file.save(os.path.join(path, filename))
            # return redirect(url_for('uploaded_file',
            #                         filename=filename))
            resp = Response("OK\n", status=200)
            return resp
    return '''
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form method="post" enctype="multipart/form-data">
      <input type="input" name="deviceid"/><br/>
      <input type="file" name="file"/><br/>
      <input type="submit" value="Upload"/>
    </form>
    '''


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=54321)
