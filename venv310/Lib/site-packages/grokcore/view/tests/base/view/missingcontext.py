"""
Views without a context cannot be grokked:

  >>> grok.testing.grok(__name__)
  Traceback (most recent call last):
    ...
  martian.error.GrokError: No module-level context for\
  <class 'grokcore.view.tests.base.view.missingcontext.Club'>, please use the\
  'context' directive.

"""

import grokcore.view as grok


class Club(grok.View):
    pass
