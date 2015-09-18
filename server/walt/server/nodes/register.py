
def node_exists(db, mac):
    return db.select_unique("nodes", mac=mac) != None

def register_node(  images, devices, db, dhcpd, \
                    mac, ip, node_type, \
                    image_fullname, current_requests):
    # insert in table devices if missing
    if not db.select_unique("devices", mac=mac):
        devices.add(type=node_type, mac=mac, ip=ip)
    # insert in table nodes
    db.insert('nodes', mac=mac, image=image_fullname)
    # refresh local cache of node images, mount needed images
    # refresh the dhcpd conf
    db.commit()
    images.refresh()
    images.update_image_mounts()
    dhcpd.update()
    # we are all done
    current_requests.remove(mac)

class RegisterNodeTask(object):
    def __init__(self, images, node_type, docker, **kwargs):
        self.images = images
        self.node_type = node_type
        self.image_fullname = images.get_default_image(node_type)
        self.docker = docker
        self.kwargs = kwargs
    def perform(self):
        # this is where things may take some time...
        if self.image_fullname not in self.images:
            self.docker.pull(self.image_fullname)
    def handle_result(self, res):
        # this should go fast
        register_node(  images = self.images,
                        node_type = self.node_type,
                        image_fullname = self.image_fullname,
                        **self.kwargs)

def handle_registration_request( \
                    blocking, db, mac, \
                    current_requests, **kwargs):
    if mac in current_requests or node_exists(db, mac):
        # this is a duplicate request, we already have registered
        # this node or it is being registered
        return
    current_requests.add(mac)
    full_kwargs = dict(
        db = db,
        mac = mac,
        current_requests = current_requests,
        **kwargs
    )
    # we may have to pull an image, that will be long,
    # let's do this asynchronously
    blocking.do(RegisterNodeTask(**full_kwargs))

class NodeRegistrationHandler(object):
    def __init__(self, blocking, sock, sock_file, **kwargs):
        self.sock_file = sock_file
        self.blocking = blocking
        self.mac = None
        self.ip = None
        self.node_type = None
        self.kwargs = kwargs

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()
    # the node register itself in its early bootup phase,
    # thus the protocol is simple: based on text lines
    def readline(self):
        return self.sock_file.readline().strip()
    # when the event loop detects an event for us, we
    # know a log line should be read.
    def handle_event(self, ts):
        if self.mac == None:
            self.mac = self.readline()
        elif self.ip == None:
            self.ip = self.readline()
        elif self.node_type == None:
            self.node_type = self.readline()
            handle_registration_request(
                blocking = self.blocking,
                mac = self.mac,
                ip = self.ip,
                node_type = self.node_type,
                **self.kwargs
            )
            # tell the event_loop that we can be removed
            return False
    def close(self):
        self.sock_file.close()
