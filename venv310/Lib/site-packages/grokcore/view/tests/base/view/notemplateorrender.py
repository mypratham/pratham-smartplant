"""
Views either need an associated template or a ``render`` method:

  >>> grok.testing.grok(__name__)
  Traceback (most recent call last):
    ...
  zope.configuration.config.ConfigurationExecutionError:\
  martian.error.GrokError: View\
  <class 'grokcore.view.tests.base.view.notemplateorrender.CavePainting'>\
  has no associated template or 'render' method.

"""

import grokcore.view as grok


class Mammoth(grok.Context):
    pass


class CavePainting(grok.View):
    pass
