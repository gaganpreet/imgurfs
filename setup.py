from distutils.core import setup
import os 

if os.path.exists('doc/mount.flickrfs.1.gz'):
    df = [('/usr/share/man/man1/', ['doc/mount.flickrfs.1.gz'])]
else:
    df = [] 

setup (install_requires = ['fuse-python>=0.2'],
       name = 'imgurfs',
       version = '0.0.1',
       description = 'Virtual filesystem for imgur',
       author = 'Gaganpreet',
       author_email = 'gaganpreet.arora@gmail.com',
       url = 'https://github.com/gaganpreet/imgurfs',
       license = 'GPL-3',
       packages = ['imgurfs'],
       package_dir = {'imgurfs' : 'src/imgurfs/'},
       scripts = ['src/mount.imgurfs'],
       data_files = df
      )
