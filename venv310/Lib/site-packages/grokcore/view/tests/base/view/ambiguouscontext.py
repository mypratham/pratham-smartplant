"""
Templates with ambiguous context cannot be grokked:

  >>> grok.testing.grok(__name__)
  Traceback (most recent call last):
    ...
  martian.error.GrokError: Multiple possible contexts for\
  <class 'grokcore.view.tests.base.view.ambiguouscontext.Club'>, please use the\
  'context' directive.

"""  # noqa: E501 line too long

import grokcore.view as grok


class Cave(grok.Context):
    pass


class Mammoth(grok.Context):
    pass


class Club(grok.View):
    pass
