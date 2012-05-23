#!/usr/bin/python
# -*- coding: utf-8 -*-

#=======================================================================
#  imgurfs - Virtual file system for Imgur
#  buf.py - Buffers for reading and uploading images
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

import urllib2
import logging
from cStringIO import StringIO

class Buffer:
    """ Manages buffers for reading and writing images from/to imgur """

    def __init__ (self):
        self.read_images = {}
        self.write_images = {}

    def read (self, link, length, offset):
        """ Download the image data to a buffer to manage reads """
        if link not in self.read_images:
            # Read the image into a buffer
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
