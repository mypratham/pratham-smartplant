"""
When a directory resource is declared, it is not allowed for it to be a
python package::

  >>> import grokcore.view as grok
  >>> grok.testing.grok(
  ...     'grokcore.view.tests.base.directoryresource.directoryispackage_fixture')
  Traceback (most recent call last):
    ...
  martian.error.GrokError: The 'foo' resource directory must not be a python package.
"""  # noqa: E501 line too long
