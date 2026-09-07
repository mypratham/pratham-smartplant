=================
HTTPFactory tests
=================

This tests that httpfactory provide the right publication class,
for each request type, defined in the configure.zcml with publisher directive.

The publication class is chosen upon the method name,
the mime type and sometimes some request headers

A regular GET, POST or HEAD

  >>> from __future__ import print_function

  >>> from zope.app.wsgi.testlayer import http

  >>> print(http(wsgi_app, b"""\
  ... GET / HTTP/1.1
  ... """))
  HTTP/1.1 200 OK
  Content-Length: ...
  Content-Type: text/html;charset=utf-8
  ...
  >>> print(http(wsgi_app, b"""\
  ... POST / HTTP/1.1
  ... """))
  HTTP/1.1 200 OK
  Content-Length: ...
  Content-Type: text/html;charset=utf-8
  ...
  >>> print(http(wsgi_app, b"""\
  ... HEAD / HTTP/1.1
  ... """))
  HTTP/1.1 200 OK
  Content-Length: 0
  Content-Type: text/html;charset=utf-8
  <BLANKLINE>

A text/xml POST request, wich is an xml-rpc call

  >>> print(http(wsgi_app, b"""\
  ... POST /RPC2 HTTP/1.0
  ... Content-Type: text/xml
  ... """))
  HTTP/1.0 200 OK
  Content-Length: ...
  Content-Type: text/xml;charset=utf-8
  ...

A text/xml POST request, with a HTTP_SOAPACTION in the headers,
wich is an xml-rpc call:

TODO need to create a real SOAP exchange test here

  >>> print(http(wsgi_app, b"""\
  ... POST /RPC2 HTTP/1.0
  ... Content-Type: text/xml
  ... HTTP_SOAPACTION: soap#action
  ... """))
  HTTP/1.0 200 OK
  Content-Length: ...
  Content-Type: text/xml;charset=utf-8
  ...

Unknown request types:

TODO need more testing here

  >>> print(http(wsgi_app, b"""\
  ... POST /BUBA HTTP/1.0
  ... Content-Type: text/topnotch
  ... """))
  HTTP/1.0 404 Not Found
  ...

