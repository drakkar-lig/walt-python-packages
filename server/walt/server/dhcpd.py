import os, bottle
from gevent.pywsgi import WSGIServer
from walt.common.tcp import write_pickle, client_sock_file, Requests
from walt.common.constants import WALT_SERVER_TCP_PORT

WALT_HTTPD_PORT = 80

WELCOME_PAGE = '''
<html>
<h2>WalT server HTTP service</h2>

Available sub-directories:
<ul>
  <li> <b>/boot</b> -- boot files to be retrieved by HTTP-capable bootloaders </li>
</ul>
</html>
'''

def fake_tftp_read(ip, path):
    # connect to server
    f = client_sock_file('localhost', WALT_SERVER_TCP_PORT)
    # send the request id
    Requests.send_id(f, Requests.REQ_FAKE_TFTP_GET)
    # wait for the READY message from the server
    f.readline()
    # write the parameters
    write_pickle(dict(
            node_ip=ip,
            path=path), f)
    # receive status
    status = f.readline().decode('UTF-8').strip()
    if status == 'OK':
        # read size
        size = int(f.readline().strip())
        print(path, size)
        # receive content
        content = b''
        while len(content) < size:
            content += f.read(size - len(content))
    else:
        content = None
    # close file and return
    f.close()
    print(path + " " + status)
    return status, content

def notify_systemd():
    if 'NOTIFY_SOCKET' in os.environ:
        import sdnotify
        sdnotify.SystemdNotifier().notify("READY=1")

def run():
    app = bottle.Bottle()
    @app.route('/')
    @app.route('/index.html')
    def welcome():
        return WELCOME_PAGE
    @app.route('/boot/<path:path>')
    def serve(path):
        client_ip = bottle.request.environ.get('REMOTE_ADDR')
        client_ip = client_ip.lstrip('::ffff:')
        status, content = fake_tftp_read(client_ip, '/'+path)
        if status == 'OK':
            return content
        elif status == 'NO SUCH FILE':
            return bottle.HTTPError(404, "No such file.")
        else:
            return bottle.HTTPError(400, status)
    server = WSGIServer(('', WALT_HTTPD_PORT), app)
    notify_systemd()
    server.serve_forever()
