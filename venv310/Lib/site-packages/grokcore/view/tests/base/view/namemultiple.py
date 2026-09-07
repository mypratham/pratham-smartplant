"""
You can't call grok.name multiple times for a view

  >>> import grokcore.view.tests.base.view.namemultiple_fixture
  Traceback (most recent call last):
    ...
  martian.error.GrokImportError: The 'name' directive can only be\
  called once per class.

"""
