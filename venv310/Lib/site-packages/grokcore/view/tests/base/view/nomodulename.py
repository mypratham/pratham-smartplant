"""
You can't call grok.name on a module:

  >>> import grokcore.view.tests.base.view.nomodulename_fixture
  Traceback (most recent call last):
    ...
  martian.error.GrokImportError: The 'name' directive can only be used on\
  class level.

"""
