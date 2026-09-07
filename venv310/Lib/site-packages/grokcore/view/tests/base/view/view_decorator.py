"""
Using the @grok.require decorator in a view class is not allowed.

  >>> grok.testing.grok(__name__)
  Traceback (most recent call last):
    ...
  martian.error.GrokError: The @grok.require decorator is used for\
  method 'render' in view\
  <class 'grokcore.view.tests.base.view.view_decorator.BogusView'>.\
  It may only be used for XML-RPC methods.


"""

import zope.interface

import grokcore.view as grok


class Bogus(grok.Permission):
    grok.name('bogus.perm')


class BogusView(grok.View):
    grok.context(zope.interface.Interface)

    @grok.require(Bogus)
    def render(self):
        pass
