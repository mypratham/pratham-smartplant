"""
The permissions() directive only accepts permission ids or permission classes:

  >>> import grokcore.security.testing
  >>>
  >>> grokcore.security.testing.grok(
  ...     'grokcore.security.tests.base.permissions.directive_fixture')
  Traceback (most recent call last):
  ...
  martian.error.GrokImportError: You can only pass unicode values, ASCII \
  values, or subclasses of grok.Permission to the 'permissions' directive.

"""
