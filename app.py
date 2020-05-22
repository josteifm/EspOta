from flask import Flask, request, send_from_directory, jsonify, Response
import hashlib
import os
import glob

app = Flask(__name__)

header_X_ESP8266_SKETCH_MD5 = 'X-ESP8266-SKETCH-MD5'
header_X_ESP8266_STA_MAC = 'X-ESP8266-STA-MAC'
header_X_ESP8266_AP_MAC = 'X-ESP8266-AP-MAC'
header_X_ESP8266_FREE_SPACE = 'X-ESP8266-FREE-SPACE'
header_X_ESP8266_SKETCH_SIZE = 'X-ESP8266-SKETCH-SIZE'
header_X_ESP8266_CHIP_SIZE = 'X-ESP8266-CHIP-SIZE'
header_X_ESP8266_SDK_VERSION = 'X-ESP8266-SDK-VERSION'

basepath = './files/'

def check_header(name, value = False):
    print(name + ' : ' + str(request.headers.get(name))) 
    if request.headers.get(name) == None:
        return False
    
    if(value and request.headers.get(name).lower() != value.lower()):
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
    
    if not check_header(header_X_ESP8266_STA_MAC) or not check_header(header_X_ESP8266_AP_MAC) or not check_header(header_X_ESP8266_FREE_SPACE) or not check_header(header_X_ESP8266_SKETCH_SIZE) or not check_header(header_X_ESP8266_SKETCH_MD5) or not check_header(header_X_ESP8266_CHIP_SIZE) or not check_header(header_X_ESP8266_SDK_VERSION):
        resp = Response("only for ESP8266 updater! (header)\n", status=403)
        return resp

    ESP8266_AP_MAC = request.headers.get(header_X_ESP8266_AP_MAC)
    ESP8266_STA_MAC = request.headers.get(header_X_ESP8266_STA_MAC)

    file_path = basepath + ESP8266_AP_MAC.replace(":","")
    if not os.path.exists(file_path):
        resp = Response("No firmware for this chip {}\n".format(ESP8266_AP_MAC), status=404)
        return resp

    files = list(filter(os.path.isfile, glob.glob(file_path + "/*")))

    print(files)
    files.sort(key=os.path.getctime)
    print(files[0])

    #get file for requesing chip
    fw_file = files[0]
    fw_md5 = md5(fw_file)

    print(fw_md5)
    fw_filename = os.path.basename(fw_file)
    print(fw_filename)

    if request.headers.get(header_X_ESP8266_SKETCH_MD5) == fw_md5:
        resp = Response("Firmware is newest version\n", status=304)
        return resp

    resp = send_from_directory(file_path, fw_filename)
    resp.headers['X-MD5'] = fw_md5
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=54321)
