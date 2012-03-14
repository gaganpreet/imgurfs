#!/usr/bin/python
#=======================================================================
#  imgurfs - Virtual file system for Imgur
#  Copyright (c) 2012 Gaganpreet  <gaganpreet.arora@gmail.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#=======================================================================

import getopt
import sys
import os
import fuse
import urllib2
import urllib
import cookielib
import simplejson
import getpass
import logging
import inspect
import time
import stat
import errno
from datetime import datetime

fuse.fuse_python_api = (0, 2)
logger = logging.getLogger('imgur-fuse')
hdlr = logging.FileHandler('imgur-fuse.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr) 
logger.setLevel(logging.DEBUG)

class Stat (fuse.Stat):
 def __init__ (self):
     self.st_mode = stat.S_IFDIR | 0755
     self.st_ino = 0
     self.st_dev = 0
     self.st_nlink = 2
     self.st_uid = os.getuid()
     self.st_gid = os.getgid()
     self.st_size = 4096
     self.st_atime = int(time.time())
     self.st_mtime = self.st_atime
     self.st_ctime = self.st_atime

class Buffer:
    """ Manages buffers for reading and writing images from/to imgur """
    read_images = {}
    write_images = {}

    def read (self, link, length, offset):
        """ Stores the image data to manage reads """
        if link not in self.read_images:
            self.read_images[link] = {"buffer": urllib2.urlopen(link).read()}
        if offset > len(self.read_images[link]["buffer"]):
            return None
        return self.read_images[link]["buffer"][offset:offset+length]

def split_path(path):
    """ Splits a path into album and image name """
    p = path.split("/");
    if len(p) > 3:
        return [None, None]
    elif len(p) == 3:
        return [p[1], p[2]]
    else:
        return [None, p[1]]

class Imgur:
    """ Wrapper for the Imgur api """
    api_endpoint = 'http://api.imgur.com/2/'
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())
    urllib2.install_opener(opener)

    # We use last_fetch to cache image list for 10 seconds
    # TODO: Make cache duration a command line option
    last_fetch = 0

    def __init__ (self, username, password):
        """ Signs into imgur """
        try:
            r = self.opener.open(self.api_endpoint + 'signin.json',
                        urllib.urlencode({'username' : username,
                                          'password' : password}));
        except urllib2.HTTPError, e:
            error = simplejson.loads(e.readline())
            if error.has_key('error'):
                print error['error']['message']
                sys.exit(0)

    def api_request (self, path, parameters = {}):
        """ Make an api request and return the result """
        if parameters == {}:
            return self.opener.open(self.api_endpoint + path);
        else:
            return self.opener.open(self.api_endpoint + path, urllib.urlencode(parameters));

    def image_count (self):
        """ Get the total number of images in user's account """
        r = self.api_request('account/images_count.json');
        result = simplejson.loads(r.readline())
        self.count = result["images_count"]["count"]
        return self.count

    def image_list (self):
        """ Returns the images in a user's account as a dictionary 
            The dictionary key is the name, if present, otherwise hash
            of the image plus it's extension

            The value of each key is another dictionary with the parameters:
            hash, size, type, datetime, deletehash
        """
        if time.time() - self.last_fetch < 10:
            return self.images
        images = [];
        self.images = {}
        
        # Images start from page 1
        for i in xrange(1, self.image_count()/100 + 2):
            r = self.api_request('account/images.json?' + urllib.urlencode({'page' : i, 'count' : 100}));
            images.extend(simplejson.loads(r.readline())["images"])

        for i in images:
            extension = "." + i["image"]["type"].split("/")[1]
            name = i["image"]["name"] or i["image"]["hash"]
            name += extension

            self.images[name] = { "hash": i["image"]["hash"],
                                  "size": i["image"]["size"],
                                  "type": i["image"]["type"],
                                  "datetime": i["image"]["datetime"],
                                  "deletehash": i["image"]["deletehash"],
                                  "link": i["links"]["original"]}
        self.last_fetch = time.time()
        return self.images

    def read_image (self, name, length, offset):
        return self.buf.read(self.images[name]["link"], length, offset)


class ImgurFS (fuse.Fuse):
    buf = Buffer()
    def __init__ (self, *args, **kw):
        """ Initialize the fuse filesystem 
            Note: run with -f parameter for debugging 
        """
        fuse.Fuse.__init__(self, *args, **kw)
        username = raw_input('Imgur username/email: ');
        password = getpass.getpass('Password: ');
        self.imgur = Imgur(username, password);
        print "Logged in"

    def getattr (self, path):
        """ Returns the attributes for the given path
            Defaults are taken from Stat class defined above
        """
        print '*** getattr', path
        st = Stat();
        album, name = split_path(path)

        if name is None:
            return - errno.ENOENT
        # Path is a file
        if name != '':
            if not self.imgur.image_list().has_key(name):
                return -errno.ENOENT
            image = self.imgur.image_list()[name];
            st.st_mode = stat.S_IFREG | 0755
            st.st_ctime = time.mktime(datetime.strptime(image["datetime"], 
                                                        "%Y-%m-%d %H:%M:%S").timetuple())
            st.st_mtime = st.st_ctime
            st.st_size = image["size"]
        return st

    def readdir (self, path, offset):
        print '*** readdir', path, offset
        """ Returns a generator for files in user's account """
        dirents = ['.', '..']
        images = self.imgur.image_list()
        for i in images:
            dirents.append(i) 
        for d in dirents:
            yield fuse.Direntry(d);

    def open (self, path, flags):
        print '*** open', path, flags
        accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR 
        if (flags & accmode) != os.O_RDONLY:
            return -errno.EACCES
    
    def read (self, path, length, offset):
        print '*** read', path, length, offset
        album, name = split_path(path);
        image = self.imgur.image_list()[name];
        return self.buf.read(image["link"], length, offset);

    def fsync ( self, path, isFsyncFile ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** fsync', path, isFsyncFile
        return -errno.ENOSYS

    def link ( self, targetPath, linkPath ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** link', targetPath, linkPath
        return -errno.ENOSYS

    def mkdir ( self, path, mode ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** mkdir', path, oct(mode)
        return -errno.ENOSYS

    def readlink ( self, path ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** readlink', path
        return -errno.ENOSYS

    def release ( self, path, flags ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** release', path, flags
        return -errno.ENOSYS

    def rename (self, oldPath, newPath):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** rename', oldPath, newPath
        return -errno.ENOSYS

    def rmdir ( self, path ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** rmdir', path
        return -errno.ENOSYS

    def statfs ( self ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** statfs'
        return -errno.ENOSYS

    def symlink ( self, targetPath, linkPath ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** symlink', targetPath, linkPath
        return -errno.ENOSYS

    def unlink ( self, path ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** unlink', path
        return -errno.ENOSYS

    def utime ( self, path, times ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** utime', path, times
        return -errno.ENOSYS

    def write ( self, path, buf, offset ):
        logger.debug(inspect.stack()[0][3] + path);
        print '*** write', path, buf, offset
        return -errno.ENOSYS
    
    """ The following operations make no sense in our filesystem """
    def chmod (self, path, mode):
        print '*** chmod', path, oct(mode)
        return -errno.ENOSYS

    def chown (self, path, uid, gid):
        print '*** chown', path, uid, gid
        return -errno.ENOSYS

    def truncate ( self, path, size ):
        print '*** truncate', path, size
        return -errno.ENOSYS

def main():
    server = ImgurFS()
    server.parse(errex=1)
    server.main()

if __name__ == '__main__':
    main()
