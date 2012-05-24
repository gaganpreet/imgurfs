#!/usr/bin/python
# -*- coding: utf-8 -*-

#=======================================================================
#  imgurfs - Virtual file system for Imgur
#  api.py - Wrapper for Imgur api
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

import sys
import urllib
import urllib2
try:
    import simplejson
except:
    import json as simplejson
import time
from base64 import b64encode

class Imgur:
    """ Wrapper for the Imgur api """

    def __init__ (self, username, password):
        """ Signs into imgur """
        # TODO: Error checking for api requests
        self.api_endpoint = 'https://api.imgur.com/2/'
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())
        urllib2.install_opener(self.opener)
 
        # We use cache to cache image and album list for 10 seconds
        # TODO: Make cache duration a command line option

        # Cache for images, album name is the key in the dictionary
        # None album points to unorganized images (/ directory)
        self.cache = {}
        # Cache for albums
        self.cache_albums = {'time': 0, 
                             'list': {}}
        try:
            r = self.opener.open(self.api_endpoint + 'signin.json',
                        urllib.urlencode({'username' : username,
                                          'password' : password}))
            # TODO: Use ratelimit in statfs
            self.ratelimit = dict(remaining = r.headers.dict['x-ratelimit-remaining'],
                                  limit = r.headers.dict['x-ratelimit-limit'])
        except urllib2.HTTPError, e:
            error = simplejson.loads(e.readline())
            if error.has_key('error'):
                print error['error']['message']
                sys.exit(0)

    def api_request (self, url, parameters = None):
        """ Make an api request and return the result """
        print 'Got api request for url ' + url

        # Make a GET request
        if parameters == None:
            r = self.opener.open(self.api_endpoint + url)
        # Make a POST request
        else:
            r = self.opener.open(self.api_endpoint + url, 
                                 urllib.urlencode(parameters))

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

            None album will return unorganized images

            The value of each key is another dictionary with the parameters:
            hash, size, type, datetime, deletehash, link
        """

        # If the album list is in cache and 
        # it's not expired, don't fetch it again
        if album in self.cache and time.time() - self.cache[album]['time'] < 100:
            print 'Using cache'
            return self.cache[album]['images']
        self.cache[album] = {'images': {}, 'time': 0}
        images = []

        if album == None:
            # Images start from page 1
            for i in xrange(1, self.images_count()/100 + 2):
                r = self.api_request('account/images.json?' + 
                                     urllib.urlencode({'page' : i, 
                                                       'count' : 100, 
                                                       'noalbum': 'true'}))
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
            name = str(name + extension) # Fuse doesn't like unicode
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

    def album_list (self, use_cache = True):
        """ Get the list of albums in a user's account """
        if 'list' in self.cache_albums and time.time() - self.cache_albums['time'] < 100 and use_cache:
            return self.cache_albums['list']
        albums = []
        self.cache_albums['list'] = {}

        for i in xrange(1, self.albums_count()/100 + 2):
            r = self.api_request('account/albums.json?' + urllib.urlencode({'page' : i, 'count' : 100}))
            albums.extend(simplejson.loads(r)['albums'])

        for i in albums:
            name = i['title'] or i['id']
            name = str(name) # Fuse doesn't like unicode
            self.cache_albums['list'][name] = dict(id = i['id'], datetime = i['datetime'])

        self.cache_albums['time'] = time.time()
        return self.cache_albums['list']

    def upload_image (self, album, name, data):
        """ Uploads an image to Imgur """
        print "Trying to upload ", album, name
        if len(data):
            try:
                r = self.api_request('account/images.json', 
                                     dict(name=name, 
                                          image=b64encode(data), 
                                          type='base64'))
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
        self.album_list(use_cache = False)

    def add_images (self, album, hashes):
        album_hash = self.cache_albums['list'][album]['id']
        self.api_request('account/albums/' + album_hash + '.json', 
                         dict(add_images = ','.join(hashes)))
