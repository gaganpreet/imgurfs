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
from base64 import b64encode
from cStringIO import StringIO
from datetime import datetime

fuse.fuse_python_api = (0, 2)

class Stat (fuse.Stat):
    """ Default stats for getattr """
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

    def __init__ (self):
        self.read_images = {}
        self.write_images = {}

    def read (self, link, length, offset):
        """ Download the image data to a buffer to manage reads """
        if link not in self.read_images:
            self.read_images[link] = dict(buffer = urllib2.urlopen(link).read())
        if offset > len(self.read_images[link]['buffer']):
            return None
        return self.read_images[link]['buffer'][offset:offset+length]

    def clear_read (self, link):
        """ Clear download buffer from memory """
        if link in self.read_images:
            self.read_images.pop(link)

    def create (self, album, name):
        """ Initialize a StringIO object for our new image in album (image upload is asynchronous) """
        if album not in self.write_images:
            self.write_images[album] = {}
        self.write_images[album][name] = {'data' : StringIO()}

    def write (self, album, name, data, offset):
        """ Write data to an image """
        f = self.write_images[album][name]['data']
        f.seek(offset)
        f.write(data)

        # Imgur doesn't allow files greater than 10 MB
        if len(f.getvalue()) > 1024*1024*10:
            f.truncate(0)
            return - errno.EFBIG
        return len(data)

    def get_data (self, album, name):
        """ Return data for the image to be uploaded """
        f = self.write_images[album][name]['data']
        return f.getvalue()

    def clear_write (self, album, name):
        """ Clear write buffer from memory """
        f = self.write_images[album].pop(name)

    def buffered_write_list (self, album):
        """ Get the list of images that are in the queue to being uploaded
            We wouldn't need it, but fuse calls getattr after create, which
            otherwise fails
        """
        if album in self.write_images:
            return self.write_images[album].keys()
        else:
            return []

class Imgur:
    """ Wrapper for the Imgur api """

    def __init__ (self, username, password):
        """ Signs into imgur """
        # TODO: Error checking for api requests
        self.api_endpoint = 'http://api.imgur.com/2/'
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())
        urllib2.install_opener(self.opener)
 
        # We use cache to cache image and album list for 10 seconds
        # TODO: Make cache duration a command line option
        self.cache = {}
        self.cache_albums = {'time': 0, 'list': {}}
        try:
            r = self.opener.open(self.api_endpoint + 'signin.json',
                        urllib.urlencode({'username' : username,
                                          'password' : password}))
        except urllib2.HTTPError, e:
            error = simplejson.loads(e.readline())
            if error.has_key('error'):
                print error['error']['message']
                sys.exit(0)

    def api_request (self, url, parameters = {}):
        """ Make an api request and return the result """
        print 'Got api request for url ' + url
        if parameters == {}:
            r = self.opener.open(self.api_endpoint + url)
        else:
            r = self.opener.open(self.api_endpoint + url, urllib.urlencode(parameters))

        self.ratelimit = dict(remaining = r.headers.dict['x-ratelimit-remaining'],
                              limit = r.headers.dict['x-ratelimit-limit'])
        return r.readline()

    def images_count (self):
        """ Get the total number of images in user's account """
        r = self.api_request('account/images_count.json')
        result = simplejson.loads(r)
        self.count = result['images_count']['count']
        return self.count

    def image_list (self, album):
        """ Returns the images in a user's account as a dictionary 
            The dictionary key is the image hash given by imgur

            None album are unorganized images

            The value of each key is another dictionary with the parameters:
            hash, size, type, datetime, deletehash, link
        """

        # If the album list is in cache and it's not expired, don't fetch it again
        if album in self.cache and time.time() - self.cache[album]['time'] < 100:
            print 'Using cache'
            return self.cache[album]['images']
        self.cache[album] = {'images': {}, 'time': 0}
        images = []

        if album == None:
            # Images start from page 1
            for i in xrange(1, self.images_count()/100 + 2):
                r = self.api_request('account/images.json?' + urllib.urlencode({'page' : i, 'count' : 100, 'noalbum': 'true'}))
                if 'images' in r:
                    images.extend(simplejson.loads(r)['images'])
        else:
            try:
                r = self.api_request('account/albums/' + self.cache_albums['list'][album]['id'] + '.json')
                if 'albums' in r:
                    images.extend(simplejson.loads(r)['albums'])
            except urllib2.HTTPError, e:
                pass

        for i in images:
            extension = '.' + i['image']['type'].split('/')[1]
            name = i['image']['name'] or i['image']['hash']
            name = name + extension
            self.cache[album]['images'][name] = dict(hash = i['image']['hash'],
                                            size = i['image']['size'],
                                            type = i['image']['type'],
                                            datetime = i['image']['datetime'],
                                            deletehash = i['image']['deletehash'],
                                            link = i['links']['original'])
        self.cache[album]['time'] = time.time()
        return self.cache[album]['images']

    def albums_count (self):
        """ Get the total number of albums in user's account """
        r = self.api_request('account/albums_count.json')
        result = simplejson.loads(r)
        self.album_count = result['albums_count']['count']
        return self.album_count

    def album_list (self, cache = False):
        """ Get the list of albums in a user's account """
        if 'list' in self.cache_albums and time.time() - self.cache_albums['time'] < 100 and not cache:
            return self.cache_albums['list']
        albums = []
        self.cache_albums['list'] = {}

        for i in xrange(1, self.albums_count()/100 + 2):
            r = self.api_request('account/albums.json?' + urllib.urlencode({'page' : i, 'count' : 100}))
            albums.extend(simplejson.loads(r)['albums'])

        for i in albums:
            name = i['title'] or i['id']
            self.cache_albums['list'][name] = dict(id = i['id'], datetime = i['datetime'])

        self.cache_albums['time'] = time.time()
        return self.cache_albums['list']

    def upload_image (self, album, name, data):
        """ Uploads an image to Imgur """
        print "Trying to upload ", album, name
        if len(data):
            try:
                r = self.api_request('account/images.json', dict(name=name, image=b64encode(data), type='base64'))
            except urllib2.HTTPError, e:
                error = simplejson.loads(e.readline())
                if 'error' in error:
                    print error['error']['message']
                    return False
            r = simplejson.loads(r)
            if 'images' in r:
                if album != None:
                    imagehash = r['images']['image']['hash']
                    self.add_images(album, [imagehash])
            else:
                print 'Something went wrong uploading the image'
                return False
        return True

    def create_album (self, album):
        self.api_request('account/albums.json', dict(title=album))
        self.album_list(True)

    def add_images (self, album, hashes):
        album_hash = self.cache_albums['list'][album]['id']
        self.api_request('account/albums/' + album_hash + '.json', dict(add_images = ','.join(hashes)))

class ImgurFS (fuse.Fuse):
    def __init__ (self, *args, **kw):
        """ Initialize the fuse filesystem 
            Note: run with -f parameter for debugging 
        """
        self.buf = Buffer()
        fuse.Fuse.__init__(self, *args, **kw)
        username = raw_input('Imgur username/email: ')
        password = getpass.getpass('Password: ')
        self.imgur = Imgur(username, password)
        print 'Logged in'

    def split_path (self, path):
        """ Splits a path into album and name, no existence checks 
            If the path points to something in /, parent is None and child is the file/dir name
            If the path is from an album, parent is album and child is the file/dir name
        """
        if path.count('/') > 2 or path == '/':
            return [None, None]
        
        relative_path = path[1:]
        if '/' in relative_path:
            return relative_path.split('/')
        else:
            return [None, relative_path]

    def parse_path(self, path):
        """ Parses a path into album and image name
            Possible inputs are:
                /
                /image_name (Belongs to None album)
                /album_name
                /album_name/image_name
            Returns a list [album_name, image_name]
        """
        # TODO: Try to write this function more concisely

        # Path can't have more than two slashes
        if path.count('/') > 2 or path == '/':
            return [None, None]

        relative_path = path[1:]
        # Test for albums or images in /, paths with one slash
        if '/' not in relative_path:
            if relative_path in self.imgur.image_list(None):
                return [None, relative_path]
            elif relative_path in self.imgur.album_list():
                return [relative_path, None]
            else:
                return [None, None]

        # Now deal paths with 2 slashes
        else:
            album, name = relative_path.split('/')
            if name in self.imgur.image_list(album):
                return [album, name]
            else:
                return [None, None]

    def getattr (self, path):
        """ Returns the attributes for the given path
            Defaults are taken from Stat class defined above
        """
        print '*** getattr', path
        st = Stat()

        print self.split_path(path)
        parent, child = self.split_path(path)
        if child in self.buf.buffered_write_list(parent):
            st.st_mode = stat.S_IFREG | 0755
            st.st_size = 0
            return st

        album, name = self.parse_path(path)

        if name == None and album == None and path != '/':
            return - errno.ENOENT

        # Add more info if path is a file
        if name != None: 
            image = self.imgur.image_list(album)[name]
            st.st_mode = stat.S_IFREG | 0755
            st.st_ctime = time.mktime(datetime.strptime(image['datetime'], 
                                                        '%Y-%m-%d %H:%M:%S').timetuple())
            st.st_mtime = st.st_ctime
            st.st_size = image['size']
        return st

    def readdir (self, path, offset):
        """ Returns a generator for files in user's account """
        print '*** readdir', path, offset
        dirents = ['.', '..']
        parent, child = self.split_path(path)
        images = self.imgur.image_list(child)
        dirents.extend(images.keys())

        if path == '/':
            albums = self.imgur.album_list()
            dirents.extend(albums.keys())

        for d in dirents:
            yield fuse.Direntry(d)

    def open (self, path, flags):
        print '*** open', path, flags
        accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR 
        if (flags & accmode) not in [os.O_RDONLY, os.O_WRONLY]:
            return -errno.EACCES
        return 0
    
    def read (self, path, length, offset):
        print '*** read', path, length, offset
        parent, child = self.split_path(path)
        image = self.imgur.image_list(parent)[child]
        return self.buf.read(image['link'], length, offset)

    def release (self, path, flags):
        """ release is called after either reading an image or writing one 
            If an upload fails, there's no feedback (errno doesn't work for release?)
        """
        print '*** release', path, flags
        parent, child = self.split_path(path)

        if child in self.buf.buffered_write_list(parent):
            result = self.imgur.upload_image(parent, child, self.buf.get_data(parent, child))
            self.buf.clear_write(parent, child)
            if result == False:
                return - errno.ENOSYS
        else:
            image = self.imgur.image_list(parent)[child]
            self.buf.clear_read(image['link'])
        return 0

    def create (self, path, flags, mode):
        print '*** create', path, flags, mode
        parent, child = self.split_path(path)
        if mode & stat.S_IFREG == 0:
            return - errno.ENOSYS
        self.buf.create(parent, child)
        return 0

    def write (self, path, data, offset):
        print '*** write', path, data, offset
        parent, child = self.split_path(path)
        return self.buf.write(parent, child, data, offset)

    def mkdir (self, path, mode):
        print '*** mkdir', path, oct(mode)
        parent, child = self.split_path(path)

        # Can't have directories (albums) at second level
        if parent != None:
            return - errno.ENOSYS
        else:
            self.imgur.create_album(child)

    def rmdir (self, path):
        print '*** rmdir', path
        parent, child = self.split_path(path)
        if len(self.imgur.image_list(child)):
            return -errno.ENOTEMPTY
        return -errno.ENOSYS

    def rename (self, oldPath, newPath):
        print '*** rename', oldPath, newPath
        return -errno.ENOSYS

    def statfs (self):
        print '*** statfs'
        st = fuse.StatVfs()
        st.f_bsize = 1
        st.f_frsize = 1
        st.f_blocks = self.imgur.ratelimit['limit']
        st.f_bfree = self.imgur.ratelimit['remaining']
        return st

    def unlink (self, path):
        print '*** unlink', path
        return -errno.ENOSYS

    """ The following operations make no sense in our filesystem """
    def chmod (self, path, mode):
        print '*** chmod', path, oct(mode)
        return -errno.ENOSYS

    def chown (self, path, uid, gid):
        print '*** chown', path, uid, gid
        return -errno.ENOSYS

    def truncate (self, path, size):
        print '*** truncate', path, size
        return -errno.ENOSYS

    def fsync (self, path, isFsyncFile):
        print '*** fsync', path, isFsyncFile
        return -errno.ENOSYS

    def link (self, targetPath, linkPath):
        print '*** link', targetPath, linkPath
        return -errno.ENOSYS

    def symlink (self, targetPath, linkPath):
        print '*** symlink', targetPath, linkPath
        return -errno.ENOSYS

    def readlink (self, path):
        print '*** readlink', path
        return -errno.ENOSYS

    def utime (self, path, times):
        print '*** utime', path, times
        return -errno.ENOSYS

def main():
    server = ImgurFS()
    server.parse(errex=1)
    server.main()

if __name__ == '__main__':
    main()
