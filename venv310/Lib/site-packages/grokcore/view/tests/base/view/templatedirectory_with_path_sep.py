"""
You can not use path separator in templatedir directive:

  >>> import grokcore.view.tests.base.view.templatedirectory_with_path_sep_fixture
  Traceback (most recent call last):
    ...
  martian.error.GrokImportError: The 'templatedir' directive can not\
  contain path separator.


"""  # noqa: E501 line too long
