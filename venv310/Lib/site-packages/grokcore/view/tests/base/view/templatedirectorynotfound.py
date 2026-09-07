"""
If the template directory you specify doesn't exist, you have a comprehensible
error:

  >>> from grokcore import view as grok
  >>> grok.testing.grok(
  ...     'grokcore.view.tests.base.view.templatedirectorynotfound_fixture')
  Traceback (most recent call last):
  ...
  martian.error.GrokImportError: The directory 'idontexit' specified by the\
  'templatedir' directive cannot be found.

"""
