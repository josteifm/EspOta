from flask import Flask, request, send_from_directory, Response
from werkzeug.utils import secure_filename
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import os
import logging
import sys

ALLOWED_EXTENSIONS = {'bin'}

app = Flask(__name__)

header_X_ESP8266_SKETCH_MD5 = 'X-ESP8266-SKETCH-MD5'
header_X_ESP8266_STA_MAC = 'X-ESP8266-STA-MAC'
header_X_ESP8266_AP_MAC = 'X-ESP8266-AP-MAC'
header_X_ESP8266_FREE_SPACE = 'X-ESP8266-FREE-SPACE'
header_X_ESP8266_SKETCH_SIZE = 'X-ESP8266-SKETCH-SIZE'
header_X_ESP8266_CHIP_SIZE = 'X-ESP8266-CHIP-SIZE'
header_X_ESP8266_SDK_VERSION = 'X-ESP8266-SDK-VERSION'

required_headers = [header_X_ESP8266_SKETCH_MD5, header_X_ESP8266_STA_MAC, header_X_ESP8266_AP_MAC, header_X_ESP8266_FREE_SPACE,
                    header_X_ESP8266_SKETCH_SIZE, header_X_ESP8266_CHIP_SIZE, header_X_ESP8266_SDK_VERSION]


def environ_or_default(key, default):
    return (
        {'default': os.environ.get(key)} if os.environ.get(key) else {'default': default}
    )


def environ_or_default_bool(key, default):
    return (
        {'default': os.environ.get(key).lower() == "true"} if os.environ.get(key) else {'default': default}
    )


def environ_or_default_int(key, default):
    return (
        {'default': int(os.environ.get(key))} if os.environ.get(key) else {'default': default}
    )


def log_setup(log_level, to_stdout=False):
    """Setup application logging"""

    numeric_level = logging.getLevelName(log_level.upper())
    if not isinstance(numeric_level, int):
        raise TypeError("Invalid log level: {0}".format(log_level))

    logging_config = {
        'format': '%(asctime)s [%(levelname)s] %(message)s',
        'level': numeric_level,
        'handlers': []
    }

    if not to_stdout:
        logging_config['handlers'].append(logging.FileHandler("logs/{:%Y-%m-%d}.log".format(datetime.now())))
        logging_config['handlers'].append(logging.StreamHandler())
    else:
        logging_config['handlers'].append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(**logging_config)
    logging.info("log_level set to: {0}".format(log_level))


def check_required_headers(req_headers):
    for h in req_headers:
        if not check_header(h):
            return False


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


def md5(file_name):
    hash_md5 = hashlib.md5()
    with open(file_name, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


@app.route('/file')
def send_file():
    # if not check_header('User-Agent', 'ESP8266-http-Update'):
    #     resp = Response("only for ESP8266 updater!\n", status=403)
    #     return resp
    debug = request.args.get('debug')

    if not debug and not check_required_headers(required_headers):
        resp = Response("only for ESP8266 updater! (header)\n", status=403)
        return resp

    esp8266_ap_mac = request.headers.get(header_X_ESP8266_AP_MAC)
    esp8266_sta_mac = request.headers.get(header_X_ESP8266_STA_MAC)
    logging.info("Request from device MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))

    file_path = app.config['UPLOAD_FOLDER'] / esp8266_ap_mac.replace(":", "")
    if not os.path.exists(file_path):
        resp = Response("No firmware for this chip {}\n".format(esp8266_ap_mac), status=404)
        logging.info("No firmware for this chip MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))
        return resp

    files = list(filter(os.path.isfile, file_path.glob("**/*")))

    print(files)
    files.sort(key=os.path.getctime)
    print(files[0])

    # get file for requesting chip
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
        device = request.form['device_id']
        print("Device: {}".format(device))
        # if user does not select file, browser also
        # submit an empty part without filename
        if device == '':
            print('No device')
            resp = Response("No device\n", status=200)
            return resp

        if file.filename == '':
            print('No selected file')
            resp = Response("No selected file\n", status=200)
            return resp

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            path = app.config['UPLOAD_FOLDER'] / device

            if not os.path.exists(path):
                os.makedirs(path)

            full_file_path = path / filename
            logging.info("Persisting file with path: {0}".format(full_file_path))
            file.save(full_file_path)
            resp = Response("OK\n", status=200)
            return resp
    return '''
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form method="post" enctype="multipart/form-data">
      <input type="input" name="device_id"/><br/>
      <input type="file" name="file"/><br/>
      <input type="submit" value="Upload"/>
    </form>
    '''


def main():
    parser = argparse.ArgumentParser(description='Esp-ota server')
    parser.add_argument('-l', '--log-level', action='store', dest='log_level',
                        help='Set log level, default: \'info\'', **environ_or_default('LOG_LEVEL', 'INFO'))
    parser.add_argument('-s', '--log-to-stdout', action='store_true', dest='log_to_stdout',
                        help='Set log level, default: \'info\'', **environ_or_default_bool('LOG_TO_STDOUT', False))
    parser.add_argument('-p', '--port', action='store', dest='port',
                        help='Set log level, default: \'info\'', **environ_or_default_int('PORT', 54321))
    parser.add_argument('-u', '--upload path', action='store', dest='upload_path',
                        help='Set upload path', **environ_or_default('UPLOAD_PATH', 'files'))
    options = parser.parse_args()

    log_setup(options.log_level, options.log_to_stdout)

    app.config['UPLOAD_FOLDER'] = Path(options.upload_path)

    logging.info("Starting OTA server on port: {0}".format(options.port))
    app.run(host='0.0.0.0', port=options.port)


if __name__ == '__main__':
    main()
