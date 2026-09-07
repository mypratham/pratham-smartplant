NotFound errors and traversal errors
====================================

Not found errors should only be displayed when someone provides a URL
to an object that doesn't exist, as in:

  >>> from __future__ import print_function

  >>> from zope.app.wsgi.testlayer import http
  >>> print(http(wsgi_app, b"""\
  ... GET /eek HTTP/1.1
  ... """))
  HTTP/1.1 404 Not Found
  ...
