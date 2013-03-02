Development
===========
I started writing this as my first major Python project, but I have had to give it up. Unfortunately, imgur's API does not make for a good filesystem. It fails quite often at my end, and is down many times altogether. Feel free to take over. 

About
=====

Imgurfs is a virtual filesystem to use imgur like a filesystem. This is mostly working except for the following things:

* Removing images
* Moving images into and out of albums
* Adding CLI options

Install
=======
1. The easy way to install is to use pip:
    `pip install imgurfs`

2. The hard way is to checkout the code and:
    `python setup.py install`
