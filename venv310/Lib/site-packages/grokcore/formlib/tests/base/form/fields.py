"""
A grok.Fields can receive keyword parameters with schema fields. These
should be available in the definition order.

  >>> grok.testing.grok(__name__)

  >>> from zope import component
  >>> from zope.publisher.browser import TestRequest
  >>> request = TestRequest()
  >>> view = component.getMultiAdapter((Mammoth(), request), name='edit')
  >>> len(view.form_fields)
  4
  >>> [w.__name__ for w in view.form_fields]
  ['a', 'b', 'g', 'd']

"""
from zope import schema

import grokcore.formlib as grok


class Mammoth(grok.Context):
    pass


class Edit(grok.EditForm):
    form_fields = grok.Fields(
        a=schema.TextLine(title="Alpha"),
        b=schema.TextLine(title="Beta"),
        g=schema.TextLine(title="Gamma"),
        d=schema.TextLine(title="Delta"))
