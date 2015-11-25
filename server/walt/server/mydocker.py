from walt.server.images.image import parse_image_fullname
from walt.server.tools import \
        display_transient_label, hide_transient_label
from walt.server import const
from docker import Client
from datetime import datetime
import sys, requests, shlex, json

def docker_command_split(cmd):
    args = shlex.split(cmd)
    return dict(
        entrypoint=args[0],
        command=args[1:]
    )

class DockerClient(object):
    def __init__(self):
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto', timeout=5)
    def self_test(self):
        try:
            self.c.search(term='walt-node')
        except:
            return False
        return True
    def pull(self, image_fullname, stdout = None):
        if stdout == None:
            stdout = sys.stdout
        fullname, name, repo, user, tag = parse_image_fullname(image_fullname)
        for idx, line in enumerate(
                self.c.pull(name, tag=requests.utils.quote(tag), stream=True)):
            progress = "\\|/-"[idx % 4]
            label = 'Downloading %s/%s... %s' % (user, tag, progress)
            display_transient_label(stdout, label)
        hide_transient_label(stdout, label)
        stdout.write('Downloading %s/%s... done.\n' % (user, tag))
    def tag(self, old_fullname, new_fullname):
        dummy1, new_name, dummy2, dummy3, new_tag = parse_image_fullname(new_fullname)
        self.c.tag(image=old_fullname, repository=new_name, tag=new_tag)
    def rmi(self, fullname):
        self.c.remove_image(image=fullname, force=True)
    def untag(self, fullname):
        self.rmi(fullname)
    def search(self, term):
        return self.c.search(term=term)
    def lookup_remote_tags(self, image_name):
        url = const.DOCKER_HUB_GET_TAGS_URL % dict(image_name = image_name)
        for elem in requests.get(url, timeout=3).json():
            tag = requests.utils.unquote(elem['name'])
            yield (image_name.split('/')[0], tag)
    def get_local_images(self):
        return sum([ i['RepoTags'] for i in self.c.images() ], [])
    def get_creation_time(self, image_fullname):
        for i in self.c.images():
            if image_fullname in i['RepoTags']:
                return datetime.fromtimestamp(i['Created'])
    def list_containers(self):
        return [ name.lstrip('/') for name in
                    sum([ cont['Names'] for cont in
                            self.c.containers(all=True) ], []) ]
    def start_container(self, image_fullname, cmd):
        params = dict(image=image_fullname)
        params.update(docker_command_split(cmd))
        cid = self.c.create_container(**params).get('Id')
        self.c.start(container=cid)
        return cid
    def wait_container(self, cid_or_cname):
        self.c.wait(container=cid_or_cname)
    def stop_container(self, cid_or_cname):
        try:
            self.c.kill(container=cid_or_cname)
        except:
            pass
        try:
            self.c.wait(container=cid_or_cname)
        except:
            pass
        try:
            self.c.remove_container(container=cid_or_cname)
        except:
            pass
    def commit(self, cid_or_cname, dest_fullname, msg):
        fullname, name, repo, user, tag = parse_image_fullname(dest_fullname)
        self.c.commit(
                container=cid_or_cname,
                repository=name,
                tag=tag,
                message=msg)
    def get_image_id(self, image_fullname):
        image_repo, image_tag = image_fullname.split(':')
        with open('/var/lib/docker/repositories-aufs') as conf_file:
            info = json.load(conf_file)
        return info['Repositories'][image_repo][image_tag]
    def get_image_layers(self, image_id):
        br = []
        while True:
            br.append('/var/lib/docker/aufs/diff/%s' % image_id)
            with open('/var/lib/docker/graph/%s/json' % image_id) as conf_file:
                info = json.load(conf_file)
            if 'parent' not in info:
                break
            else:
                image_id = info['parent']
        return br
