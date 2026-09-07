Method Not Allowed errors
=========================

If we get a request with a method that does not have a corresponding
view,  HTTP 405 Method Not Allowed response is returned:

  >>> from __future__ import print_function

  >>> from zope.app.wsgi.testlayer import http

  >>> print(http(wsgi_app, b"""\
  ... FROG / HTTP/1.1
  ... """))
  HTTP/1.1 405 Method Not Allowed
  Allow: DELETE, OPTIONS, PUT
  Content-Length: 18
  ...

  >>> print(http(wsgi_app, b"""\
  ... DELETE / HTTP/1.1
  ... """))
  HTTP/1.1 405 Method Not Allowed
  ...

Trying to PUT on an object which does not support PUT leads to 405:

  >>> print(http(wsgi_app, b"""\
  ... PUT / HTTP/1.1
  ... Authorization: Basic mgr:mgrpw
  ... """))
  HTTP/1.1 405 Method Not Allowed
  ...

Trying to PUT a not existing object on a container which does not support
PUT leads to 405:

  >>> print(http(wsgi_app, b"""\
  ... PUT /asdf HTTP/1.1
  ... Authorization: Basic mgr:mgrpw
  ... """))
  HTTP/1.1 405 Method Not Allowed
  ...

When ``handle_errors`` is set to ``False`` a traceback is displayed:

  >>> print(http(wsgi_app, b"""\
  ... PUT / HTTP/1.1
  ... Authorization: Basic mgr:mgrpw
  ... """, handle_errors=False))
  Traceback (most recent call last):
  MethodNotAllowed: <...Folder object at 0x...>, <zope.publisher.http.HTTPRequest instance URL=http://localhost>
