"""
A form view can completely override which fields are displayed by setting
form_fields manually:

  >>> grok.testing.grok(__name__)

We only expect a single field to be present in the form, as we omitted 'size':

  >>> from zope import component
  >>> from zope.publisher.browser import TestRequest
  >>> request = TestRequest()
  >>> view = component.getMultiAdapter((Mammoth(), request), name='edit')
  >>> len(view.form_fields)
  1
  >>> [w.__name__ for w in view.form_fields]
  ['name']

"""

from zope import schema
from zope.interface import Interface
from zope.interface import implementer

import grokcore.formlib as grok


class IMammoth(Interface):
    name = schema.TextLine(title="Name")
    size = schema.TextLine(title="Size", default="Quite normal")


@implementer(IMammoth)
class Mammoth(grok.Context):
    pass


class Edit(grok.EditForm):
    grok.context(Mammoth)

    form_fields = grok.Fields(IMammoth).omit('size')
