"""
You can only pass unicode to `grok.name`:

  >>> pass_unicode()
  >>> pass_encodedstring()
  Traceback (most recent call last):
    ...
  martian.error.GrokImportError: The 'name' directive can only be called with\
  unicode or ASCII.

  >>> pass_object()
  Traceback (most recent call last):
    ...
  martian.error.GrokImportError: The 'name' directive can only be called with\
  unicode or ASCII.

"""
import grokcore.view as grok


def pass_unicode():
    class View:
        grok.name('name')


def pass_encodedstring():
    class View:
        # A name as bytes is not allowed:
        grok.name("ölkj".encode('latin-1'))


def pass_object():
    class View:
        grok.name(object())
