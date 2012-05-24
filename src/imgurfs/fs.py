#!/usr/bin/python
# -*- coding: utf-8 -*-

#=======================================================================
#  imgurfs - Virtual file system for Imgur
#  fs.py - Main filesystem class
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

import os
import fuse
import getpass
import time
import stat
import errno
from datetime import datetime
from buf import Buffer
from api import Imgur

fuse.fuse_python_api = (0, 2)

def split_path (path):
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

class ImgurFS (fuse.Fuse):
    """ Main class for Imgur filesystem """
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

        print split_path(path)
        parent, child = split_path(path)
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
        parent, child = split_path(path)
        images = self.imgur.image_list(child)
        dirents.extend(images.keys())

        if path == '/':
            albums = self.imgur.album_list()
            dirents.extend(albums.keys())

        for d in dirents:
            yield fuse.Direntry(d)

    def open (self, path, flags):
        """ Open a file handler """
        print '*** open', path, flags
        accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR 
        if (flags & accmode) not in [os.O_RDONLY, os.O_WRONLY]:
            return -errno.EACCES
        return 0
    
    def read (self, path, length, offset):
        """ Read length bytes starting from offset and return """
        print '*** read', path, length, offset
        parent, child = split_path(path)
        image = self.imgur.image_list(parent)[child]
        return self.buf.read(image['link'], length, offset)

    def release (self, path, flags):
        """ release is called after either reading an image or writing one 
            If an upload fails, there's no feedback (errno doesn't work for release?)
        """
        print '*** release', path, flags
        parent, child = split_path(path)

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
        """ Create a file with flags and mode """
        print '*** create', path, flags, mode
        parent, child = split_path(path)
        if mode & stat.S_IFREG == 0:
            return - errno.ENOSYS
        self.buf.create(parent, child)
        return 0

    def write (self, path, data, offset):
        """ Write data to create'ed file """
        print '*** write', path, data, offset
        parent, child = split_path(path)
        return self.buf.write(parent, child, data, offset)

    def mkdir (self, path, mode):
        """ Create a new directory (an album) """
        print '*** mkdir', path, oct(mode)
        parent, child = split_path(path)

        # Can't have directories (albums) at second level
        if parent != None:
            return - errno.ENOSYS
        else:
            self.imgur.create_album(child)

    def rmdir (self, path):
        """ Remove a directory (album) """
        print '*** rmdir', path
        parent, child = split_path(path)
        if len(self.imgur.image_list(child)):
            return -errno.ENOTEMPTY
        return -errno.ENOSYS

    def rename (self, old_path, new_path):
        """ Handle:
            * Move an image out of an album
            * Move an image into an album
            * Rename an album
            * Move an image out of one album into another album
            """
        print '*** rename', old_path, new_path

        old_parent, old_child = split_path(old_path)
        new_parent, new_child = split_path(new_path)

        return -errno.ENOSYS

    def statfs (self):
        """ Returns API limit remaining as statfs """
        print '*** statfs'
        st = fuse.StatVfs()
        st.f_bsize = 1
        st.f_frsize = 1
        st.f_blocks = self.imgur.ratelimit['limit']
        st.f_bfree = self.imgur.ratelimit['remaining']
        return st

    def unlink (self, path):
        """ Remove an image """
        print '*** unlink', path
        return -errno.ENOSYS
