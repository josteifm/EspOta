import requests
import time 

#Add reference to this script in extra_scripts in platformIO env config
#Example
# [env:d1_mini]
# platform = espressif8266
# board = d1_mini
# framework = arduino
# extra_scripts = post:scripts/post.py


Import("env", "projenv")

print("Post build scripts")

timestamp = time.time()

def after_bin(source, target, env):
    print("after_bin")
    firmware_path = str(target[0])
    print(firmware_path)
    with open(firmware_path, 'rb') as f:
        url = 'http://localhost:54321/upload'
        files = {'file': ('devicename_{}.bin'.format(timestamp), f)}
        r = requests.post(url, data={'device_id':'devicename'}, files=files)
        print(r.text)

env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", after_bin)