from flask import Flask, request, send_from_directory, Response
from werkzeug.utils import secure_filename
from datetime import datetime
from github import Github, GithubException
from pathlib import Path
from yamlreader import yaml_load
import argparse
import hashlib
import os
import logging
import requests
import shutil
import sys
import ctypes

ALLOWED_EXTENSIONS = {'bin'}

app = Flask(__name__)

header_X_ESP8266_SKETCH_MD5 = 'X-ESP8266-SKETCH-MD5'
header_X_ESP8266_STA_MAC = 'X-ESP8266-STA-MAC'
header_X_ESP8266_AP_MAC = 'X-ESP8266-AP-MAC'
header_X_ESP8266_FREE_SPACE = 'X-ESP8266-FREE-SPACE'
header_X_ESP8266_SKETCH_SIZE = 'X-ESP8266-SKETCH-SIZE'
header_X_ESP8266_CHIP_SIZE = 'X-ESP8266-CHIP-SIZE'
header_X_ESP8266_SDK_VERSION = 'X-ESP8266-SDK-VERSION'

github = Github()
LATEST_VERSION = 'latest'
DEFAULT_FILE_NAME = 'firmware.bin'

required_headers = [header_X_ESP8266_SKETCH_MD5, header_X_ESP8266_STA_MAC, header_X_ESP8266_AP_MAC, header_X_ESP8266_FREE_SPACE,
                    header_X_ESP8266_SKETCH_SIZE, header_X_ESP8266_CHIP_SIZE, header_X_ESP8266_SDK_VERSION]


def _has_github_config(mac):
    if mac in app.config['DEVICES'] and app.config['DEVICES'][mac]:
        return True
    else:
        return False


def _get_github_release(repo, version):
    repo = github.get_repo(repo)
    if version == LATEST_VERSION:
        return repo.get_latest_release()
    else:
        releases = repo.get_releases()
        releases_as_list = list(releases)
        release_list = [r for r in releases_as_list if r.title == version]
        if len(release_list) == 1:
            return release_list[0]
        elif len(release_list) == 0:
            raise TypeError("No releases found in repo: {0}, with version: {1}, Got: {2}"
                            .format(repo, version, [r.tag_name for r in releases_as_list]))
        else:
            raise TypeError("Multiple releases found in repo: {0}, with version: {1}, {2}".format(repo, version, release_list))


def _download_github_asset_if_needed(file_path, asset):
    if not os.path.exists(file_path):
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        http_headers = {'Authorization': 'token ' + app.config['GITHUB_TOKEN'],
                        'Accept': 'application/octet-stream'}
        session = requests.Session()
        response = session.get(asset.url, headers=http_headers)
        save_to = file_path
        logging.debug("Downloading {0} from github to path: {1}".format(asset.name, file_path))
        saved_bytes = save_to.write_bytes(response.content)
        if saved_bytes != asset.size:
            logging.error("Failed to fetch artifact: {0}, from {1}".format(asset.name, asset.url))
            if os.path.exists(file_path):
                with open(file_path, 'r') as reader:
                    logging.error("File content:")
                    logging.error("File content:\n{0}".format(reader.read()))
                os.remove(file_path)

            raise ValueError("Mismatch between bytes saved and size of asset: Expected: {0}, got: {1}".format(saved_bytes, asset.size))
    return file_path


def _get_github_release_file_path(mac):
    device_config = app.config['DEVICES'][mac]
    release = _get_github_release(device_config['repo'], device_config['version'])
    if 'file-name' in device_config and device_config['file-name']:
        file_name = device_config['file-name']
    else:
        file_name = DEFAULT_FILE_NAME

    asset_list = [a for a in release.get_assets() if a.name == file_name]
    if len(asset_list) == 1:
        logging.debug("Will attempt to serve {0} from {1}:{2} for chip with MAC: {3} based on config"
                      .format(file_name, device_config['repo'], release.tag_name, mac))
        asset = asset_list[0]
    elif len(asset_list) == 0:
        raise TypeError("No files found in release: {0}:{1}, with file name: {2}".
                        format(device_config['repo'], device_config['version'], file_name))
    else:
        raise TypeError("Multiple files found in release: {0}:{1}, with file name: {2}, {3}".
                        format(device_config['repo'], device_config['version'], file_name, asset_list))

    file_path = app.config['UPLOAD_FOLDER'] / 'github' / device_config['repo'] / release.tag_name / file_name
    return _download_github_asset_if_needed(file_path, asset)


def _get_github_releases(repo):
    try:
        repo = github.get_repo(repo)
        return repo.get_releases()
    except GithubException:
        logging.exception(f'Failed to get releases for repo with name: {repo}')
        return False


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


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

    return True


def check_header(name, value=None):
    logging.debug("{0} : {1}".format(name, str(request.headers.get(name))))
    if request.headers.get(name) is None:
        return False

    if value and request.headers.get(name).lower() != value.lower():
        return False

    return True


def _create_symlink(link_name, target):
    if not target.exists():
        raise FileNotFoundError("Target must exist")
    target_is_directory = target.is_dir()
    logging.info("Creating link: : link_name: {0} - target: {1}".format(link_name, target))

    if not link_name.parent.exists():
        logging.debug("One or more parent directories missing, creating them: {0}".format(link_name.parent))
        link_name.parent.mkdir(parents=True)

    if link_name.suffix == '.bin' and target_is_directory:
        raise ValueError("If link name is a .bin file, target should be a file, not a directory")

    if link_name.is_dir():
        if list(link_name.glob('**/*')):
            raise ValueError("link name must not exist, or be an empty directory")
        else:
            logging.info("Link name existed, but was an empty dir. Removing it. link_name: {0}".format(link_name))
            shutil.rmtree(link_name)

    if os.name == 'nt' and not _is_admin():
        logging.warning("Creating symlinks on windows requires elevated rights. Skipping.")
    else:
        link_name.symlink_to(target.absolute(), target_is_directory=target_is_directory)


def _delete_symlink(link_name):
    if not link_name.is_symlink():
        raise FileNotFoundError("File is not symlink")
    logging.info("Deleting link: : link_name: {0}".format(link_name))

    if os.name == 'nt' and not _is_admin():
        logging.warning("Deleting symlinks on windows requires elevated rights. Skipping.")
    else:
        link_name.unlink()


@app.route('/')
def hello_world():
    return 'Hello, World!'


@app.route('/api/v1.0/link/<path:link_name>', methods=['GET'])
def create_link(link_name):
    target = request.args.get('target')
    if not target:
        logging.error("Unable to create symlink: link_name: {0} - target: {1}".format(link_name, target))
        return Response("Bad Request\n", status=400)

    if link_name.startswith('..'):
        logging.error("path can not start with '..' device: {0}".format(link_name))
        return Response("Bad Request\n", status=400)

    if target.startswith('..'):
        logging.error("target can not start with '..' device: {0}".format(target))
        return Response("Bad Request\n", status=400)

    logging.debug("Got request to create symlink: link_name: {0} - target: {1}".format(link_name, target))
    target_path = app.config['UPLOAD_FOLDER'] / target
    link_path = app.config['UPLOAD_FOLDER'] / link_name
    _create_symlink(link_path, target_path)
    return Response("Created\n", status=201)


@app.route('/api/v1.0/reload', methods=['GET'])
def reload_config_from_disk():
    app.config['DEVICES'] = yaml_load(app.config['CONFIG_LOCATION'], {})
    return Response("Reloaded\n", status=200)


@app.route('/api/v1.0/link/<path:link_name>', methods=['DELETE'])
def delete_link(link_name):
    if link_name.startswith('..'):
        logging.error("path can not start with '..' device: {0}".format(link_name))
        return Response("Bad Request\n", status=400)

    logging.debug("Got request to delete symlink: link_name: {0}".format(link_name))
    link_path = app.config['UPLOAD_FOLDER'] / link_name
    _delete_symlink(link_path)
    return Response("Deleted\n", status=200)


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

    if _has_github_config(esp8266_ap_mac):
        logging.info("Config found for chip with MAC {0}, serving fw from Github".format(esp8266_ap_mac))
        file_path = _get_github_release_file_path(esp8266_ap_mac)
        if not os.path.exists(file_path):
            resp = Response("No firmware for this chip {}\n".format(esp8266_ap_mac), status=404)
            logging.info("No firmware for this chip MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))
            return resp

        fw_file = file_path
        file_path = file_path.parent
    else:
        file_path = app.config['UPLOAD_FOLDER'] / esp8266_ap_mac.replace(":", "")

        if not os.path.exists(file_path):
            resp = Response("No firmware for this chip {}\n".format(esp8266_ap_mac), status=404)
            logging.info("No firmware for this chip MAC AP: {} MAC STA: {}".format(esp8266_ap_mac, esp8266_sta_mac))
            return resp

        files = list(filter(os.path.isfile, file_path.glob("**/*")))

        logging.debug("Found {0} files".format(len(files)))
        logging.debug(files)
        files.sort(key=os.path.getctime, reverse=True)
        logging.debug("Newest file based on ctime: {0}".format(files[0]))

        # get file for requesting chip
        fw_file = files[0]

    fw_md5 = md5(fw_file)
    fw_filename = os.path.basename(fw_file)
    logging.debug("MD5 for file: {0} - {1}".format(fw_filename, fw_md5))

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
            logging.error('No device')
            resp = Response("No device\n", status=200)
            return resp

        if file.filename == '':
            logging.error('No selected file')
            resp = Response("No selected file\n", status=200)
            return resp

        if device.startswith('..'):
            logging.error("path can not start with '..' device: {0}".format(device))
            return Response("Bad Request\n", status=400)

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
    parser.add_argument('-c', '--config', action='store', dest='config',
                        help='Config directory', **environ_or_default('CONFIG_DIR', 'config.yaml'))
    parser.add_argument('-g', '--github-token', action='store', dest='github_token',
                        help='Github token', **environ_or_default('GITHUB_TOKEN', False))
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

    global github
    if options.github_token:
        github = Github(options.github_token)
        app.config['GITHUB_TOKEN'] = options.github_token

    app.config['UPLOAD_FOLDER'] = Path(options.upload_path)
    app.config['CONFIG_LOCATION'] = options.config
    app.config['DEVICES'] = yaml_load(app.config['CONFIG_LOCATION'], {})

    logging.info("Starting OTA server on port: {0}".format(options.port))
    app.run(host='0.0.0.0', port=options.port)


if __name__ == '__main__':
    main()
